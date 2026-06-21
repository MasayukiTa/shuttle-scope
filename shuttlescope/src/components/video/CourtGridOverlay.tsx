/**
 * CourtGridOverlay — 定点カメラ透視補正コートグリッド
 *
 * 4コーナー＋ネット支柱2点から 18マス（各サイド 3列×3行）の
 * コートグリッドをビデオ上に SVG でオーバーレイする。
 *
 * キャリブレーション点:
 *   0: コート左上   1: コート右上
 *   2: コート右下   3: コート左下
 *   4: ネット左支柱  5: ネット右支柱
 *
 * 保存: localStorage `court-calib-{matchId}`
 * 操作:
 *   - キャリブレーションモード: 順番にクリックして6点を設定
 *   - ドラッグで任意のタイミングに点を調整可能
 *   - visible=false でグリッド非表示（点も非表示）
 */

import { useState, useRef, useEffect, useCallback, RefObject } from 'react'
import { apiGet, API_BASE_URL, getAuthHeaders } from '@/api/client'
import { useTranslation } from 'react-i18next'
import { MIcon } from '@/components/common/MIcon'

// バックエンド保存のクライアント側タイムアウト (ms)。
// fetch 自体にはタイムアウトが無いため、backend が無応答だと "DBへ保存中..." が
// 永久に表示され続けてしまう不具合があった。AbortController で 30 秒で切る。
const SAVE_TIMEOUT_MS = 30_000

// ─── 型 ─────────────────────────────────────────────────────────────────────

type Pt = { x: number; y: number }  // コンテナ基準の正規化座標 [0, 1]

interface CourtGridOverlayProps {
  matchId: string
  containerRef: RefObject<HTMLDivElement>
  /** グリッド全体の表示/非表示 */
  visible: boolean
  /** バックエンドへのキャリブレーション保存成功時のコールバック */
  onCalibrationSaved?: () => void
  /** キャリブレーション保存状態変更通知（'backend'=DB保存済 / 'local'=ローカルのみ / 'none'） */
  onCalibSourceChange?: (source: 'backend' | 'local' | 'none') => void
}

// ─── 定数 ────────────────────────────────────────────────────────────────────

// i18n キー (render 時に t() で解決する。module-scope での t() 呼び出しは禁止)
const POINT_LABEL_KEYS = [
  'auto.CourtGridOverlay.pt_court_tl', 'auto.CourtGridOverlay.pt_court_tr',
  'auto.CourtGridOverlay.pt_court_br', 'auto.CourtGridOverlay.pt_court_bl',
  'auto.CourtGridOverlay.pt_net_left', 'auto.CourtGridOverlay.pt_net_right',
]

const TOTAL_POINTS = 6
const GRID_ROWS = 3   // 各サイド3行
const GRID_COLS = 3   // 3列

const COLORS = {
  grid:      '#ffffff',   // 白 — 黒アウトラインで明暗どちらの背景でも視認
  net:       '#ff9900',   // オレンジ
  point:     '#ffff00',
  nextPoint: '#00ff88',
  text:      '#ffffff',
}

const STORAGE_KEY = (id: string) => `court-calib-${id}`

// ─── ユーティリティ ────────────────────────────────────────────────────────

function lerp(a: Pt, b: Pt, t: number): Pt {
  return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t }
}

/**
 * 台形（TL, TR, BR, BL）の内側を GRID_ROWS × GRID_COLS に分割する SVG line 要素群。
 * 透視変換では直線同士の直線性が保たれるため、lerp だけで正確なグリッドになる。
 */
function halfGridLines(
  TL: Pt, TR: Pt, BR: Pt, BL: Pt,
  w: number, h: number,
  includeOuter = true,
): Array<{ x1: number; y1: number; x2: number; y2: number }> {
  const lines: Array<{ x1: number; y1: number; x2: number; y2: number }> = []

  const startR = includeOuter ? 0 : 1
  const _endR = includeOuter ? GRID_ROWS : GRID_ROWS - 1
  const _startC = includeOuter ? 0 : 1
  const _endC = includeOuter ? GRID_COLS : GRID_COLS - 1

  // 横線 (v direction)
  for (let r = startR; r <= GRID_ROWS; r++) {
    if (!includeOuter && (r === 0 || r === GRID_ROWS)) continue
    const v = r / GRID_ROWS
    const left = lerp(TL, BL, v)
    const right = lerp(TR, BR, v)
    lines.push({ x1: left.x * w, y1: left.y * h, x2: right.x * w, y2: right.y * h })
  }
  // 縦線 (u direction)
  for (let c = 0; c <= GRID_COLS; c++) {
    if (!includeOuter && (c === 0 || c === GRID_COLS)) continue
    const u = c / GRID_COLS
    const top = lerp(TL, TR, u)
    const bottom = lerp(BL, BR, u)
    lines.push({ x1: top.x * w, y1: top.y * h, x2: bottom.x * w, y2: bottom.y * h })
  }
  return lines
}

// ─── コンポーネント ────────────────────────────────────────────────────────

type CalibSource = 'backend' | 'local' | 'none'

export function CourtGridOverlay({ matchId, containerRef, visible, onCalibrationSaved, onCalibSourceChange }: CourtGridOverlayProps) {
  const { t } = useTranslation()
  const [points, setPoints] = useState<Pt[]>([])          // 設定済み点（最大6個）
  const [calibrating, setCalibrating] = useState(false)   // キャリブレーションモード
  const [draggingIdx, setDraggingIdx] = useState<number | null>(null)
  const [containerSize, setContainerSize] = useState({ w: 1, h: 1 })
  const [savedNotice, setSavedNotice] = useState(false)   // 保存完了 & YOLO再実行案内
  const [saveError, setSaveError] = useState<string | null>(null)  // 保存エラーメッセージ
  const [saving, setSaving] = useState(false)             // 保存中スピナー
  const [calibSource, setCalibSource] = useState<CalibSource>('none') // 取得元

  // calibSource が変わるたびに親へ通知
  useEffect(() => { onCalibSourceChange?.(calibSource) }, [calibSource, onCalibSourceChange])
  const svgRef = useRef<SVGSVGElement>(null)
  const postTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const prevPtsRef = useRef<Pt[]>([])   // 再キャリブレーション開始前のバックアップ

  const isCalibrated = points.length === TOTAL_POINTS
  const nextPointIdx = calibrating ? points.length : null  // 次に設定する点のインデックス

  // ─── コンテナサイズ監視 ────────────────────────────────────────────────

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const update = () => setContainerSize({ w: el.clientWidth || 1, h: el.clientHeight || 1 })
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [containerRef])

  // ─── 読み込み: バックエンド優先 → localStorage フォールバック ─────────

  useEffect(() => {
    let cancelled = false
    setCalibSource('none')
    // 旧実装は相対 URL `/api/...` を fetch していたが、Electron の renderer は
    // file:// or app:// origin で動くため相対 URL では backend に届かず "Failed
    // to fetch" になっていた。apiGet 経由で http://localhost:8765/api を使う。
    apiGet<{ data?: { points?: [number, number][] } }>(`/matches/${matchId}/court_calibration`)
      .then((res) => {
        if (cancelled) return
        const raw: [number, number][] = res?.data?.points ?? []
        if (raw.length === TOTAL_POINTS) {
          const pts = raw.map(([x, y]) => ({ x, y }))
          setPoints(pts)
          setCalibSource('backend')
          try { localStorage.setItem(STORAGE_KEY(matchId), JSON.stringify(pts)) } catch { /* ignore */ }
        }
      })
      .catch(() => {
        // バックエンド未設定 → localStorage フォールバック
        if (cancelled) return
        try {
          const saved = localStorage.getItem(STORAGE_KEY(matchId))
          if (saved) {
            setPoints(JSON.parse(saved))
            setCalibSource('local')
          }
        } catch { /* ignore */ }
      })
    return () => { cancelled = true }
  }, [matchId])

  // 進行中の保存リクエストを abort できるよう ref で保持
  const saveAbortRef = useRef<AbortController | null>(null)

  const postToBackend = useCallback((pts: Pt[]) => {
    // 既に走っている保存があれば打ち切る (連続ドラッグの古い request 防止)
    if (saveAbortRef.current) {
      try { saveAbortRef.current.abort() } catch { /* ignore */ }
    }
    const ac = new AbortController()
    saveAbortRef.current = ac
    setSaving(true)
    // 30 秒で client-side timeout — backend 無応答時に spinner が永久残るのを防ぐ
    const timeoutId = setTimeout(() => {
      try { ac.abort() } catch { /* ignore */ }
    }, SAVE_TIMEOUT_MS)

    // apiPost は AbortSignal を渡せないため fetch を直接叩く。
    // 仕様 (URL / ヘッダ / ボディ shape) は apiPost と同等。
    fetch(`${API_BASE_URL}/matches/${matchId}/court_calibration`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
      body: JSON.stringify({
        points: pts.map((p) => ({ x: p.x, y: p.y })),
        container_width:  containerSize.w,
        container_height: containerSize.h,
      }),
      signal: ac.signal,
    })
      .then(async (res) => {
        if (!res.ok) {
          const text = await res.text().catch(() => '')
          const err = new Error(text || res.statusText) as Error & { status?: number }
          err.status = res.status
          throw err
        }
        setSaveError(null)
        setCalibSource('backend')
        setSavedNotice(true)
        setTimeout(() => setSavedNotice(false), 6000)
        onCalibrationSaved?.()
      })
      .catch((err: unknown) => {
        // AbortError: タイムアウト or 新リクエストで上書きされたケース
        const name = (err as { name?: string })?.name
        if (name === 'AbortError') {
          // timeout 由来 (タイマーがまだ生きていない = 既に発火している) なら errorMessage を出す。
          // 新リクエストで上書きされた場合は次の postToBackend が saving を立て直すのでメッセージ不要。
          if (ac === saveAbortRef.current) {
            setSaveError('DB保存タイムアウト (30秒) — バックエンドが応答しません。バックエンドを再起動後に再試行してください。')
          } else {
            return  // 上書きされた古い request — 何もしない
          }
        } else {
          const status = (err as { status?: number })?.status
          const msg = err instanceof Error ? err.message : String(err)
          console.warn('[CourtGrid] backend save failed:', status, msg)
          setSaveError(
            status
              ? (status >= 500
                  ? `DB保存失敗 (${status}) — バックエンドを再起動後に再試行してください`
                  : `DB保存失敗 (${status}): ${msg.slice(0, 200)}`)
              : `ネットワークエラー: ${msg}`,
          )
        }
        // エラーメッセージは 12 秒表示 (コピー操作に十分な時間)
        setTimeout(() => setSaveError(null), 12000)
      })
      .finally(() => {
        clearTimeout(timeoutId)
        // 自分自身が最新の controller である場合のみ saving を解除
        if (ac === saveAbortRef.current) {
          setSaving(false)
          saveAbortRef.current = null
        }
      })
  }, [matchId, containerSize, onCalibrationSaved])

  // アンマウント時に進行中保存を abort してメモリリーク防止
  useEffect(() => {
    return () => {
      if (saveAbortRef.current) {
        try { saveAbortRef.current.abort() } catch { /* ignore */ }
      }
    }
  }, [])

  const savePts = useCallback((pts: Pt[]) => {
    setPoints(pts)
    try { localStorage.setItem(STORAGE_KEY(matchId), JSON.stringify(pts)) } catch { /* ignore */ }
    // 6点揃ったらバックエンドへ debounce 保存（ドラッグ中の連打を防ぐ）
    if (pts.length === TOTAL_POINTS) {
      if (postTimerRef.current) clearTimeout(postTimerRef.current)
      postTimerRef.current = setTimeout(() => postToBackend(pts), 400)
    }
  }, [matchId, postToBackend])

  // ─── キャリブレーション操作 ────────────────────────────────────────────

  const startCalibration = useCallback(() => {
    prevPtsRef.current = points   // キャンセル用バックアップ
    setPoints([])
    setCalibSource('none')
    localStorage.removeItem(STORAGE_KEY(matchId))
    setCalibrating(true)
  }, [matchId, points])

  const getSVGPoint = useCallback((e: React.PointerEvent<SVGSVGElement>): Pt => {
    const rect = svgRef.current!.getBoundingClientRect()
    return {
      x: (e.clientX - rect.left) / rect.width,
      y: (e.clientY - rect.top) / rect.height,
    }
  }, [])

  const handleSVGPointerDown = useCallback((e: React.PointerEvent<SVGSVGElement>) => {
    // SVG クリックではキャリブレーションを開始しない（明示的なボタンで操作）
    if (!calibrating) return
    if (points.length >= TOTAL_POINTS) return
    e.preventDefault()
    const pt = getSVGPoint(e)
    const next = [...points, pt]
    if (next.length === TOTAL_POINTS) {
      savePts(next)
      setCalibrating(false)
    } else {
      setPoints(next)
    }
  }, [calibrating, points, getSVGPoint, savePts])

  // ─── ドラッグで点を調整 ─────────────────────────────────────────────────

  const handlePointPointerDown = useCallback((e: React.PointerEvent<SVGCircleElement>, idx: number) => {
    if (calibrating) return  // キャリブレーション中は干渉しない
    e.stopPropagation()
    e.currentTarget.setPointerCapture(e.pointerId)
    setDraggingIdx(idx)
  }, [calibrating])

  const handleSVGPointerMove = useCallback((e: React.PointerEvent<SVGSVGElement>) => {
    if (draggingIdx === null) return
    e.preventDefault()
    const pt = getSVGPoint(e)
    const next = points.map((p, i) => (i === draggingIdx ? pt : p))
    savePts(next)
  }, [draggingIdx, points, getSVGPoint, savePts])

  const handleSVGPointerUp = useCallback(() => {
    setDraggingIdx(null)
  }, [])

  // ─── グリッド計算 ──────────────────────────────────────────────────────

  const { w, h } = containerSize

  // 6点が揃っている場合のグリッドライン
  const gridLines: Array<{ x1: number; y1: number; x2: number; y2: number; isNet?: boolean }> = []
  if (isCalibrated) {
    const [TL, TR, BR, BL, NL, NR] = points

    // 上サイドの4隅: TL, TR, NR, NL
    const topLines = halfGridLines(TL, TR, NR, NL, w, h)
    gridLines.push(...topLines)

    // 下サイドの4隅: NL, NR, BR, BL（外周含む。ネット上辺はオレンジで上書きされる）
    const botLines = halfGridLines(NL, NR, BR, BL, w, h, true)
    gridLines.push(...botLines)

    // コート外周 (上サイドのtopライン + 下サイドのbottomライン + 左右)
    // halfGridLines の includeOuter=true で既に含まれている

    // ネットライン (別色)
    gridLines.push({ x1: NL.x * w, y1: NL.y * h, x2: NR.x * w, y2: NR.y * h, isNet: true })
  }

  // ─── 表示制御 ────────────────────────────────────────────────────────────

  // グリッドが非表示かつキャリブレーション中でもない → オーバーレイ全体を非表示
  if (!visible && !calibrating) return null

  return (
    <>
    <div
      className="absolute inset-0 pointer-events-none"
      // キャリブレーション中は ROI オーバーレイ (zIndex:30, pointer-events:auto) より
      // 上に来るよう zIndex を上げる。これをやらないと「解析領域指定中はグリッド線が
      // 描けない」不具合 (ROI overlay がクリックを横取りしてしまう) が起きる。
      // 非キャリブレーション時は 20 のまま — ROI 編集を邪魔しない。
      style={{ zIndex: calibrating ? 35 : 20 }}
    >
      <svg
        ref={svgRef}
        width="100%"
        height="100%"
        style={{
          position: 'absolute',
          inset: 0,
          pointerEvents: (calibrating || (isCalibrated && visible)) ? 'all' : 'none',
          cursor: calibrating
            ? 'crosshair'
            : draggingIdx !== null
              ? 'grabbing'
              : 'default',
        }}
        onPointerDown={handleSVGPointerDown}
        onPointerMove={handleSVGPointerMove}
        onPointerUp={handleSVGPointerUp}
      >
        {/* ─── グリッドライン（黒アウトライン先に描画 → 白線を重ねる）────── */}
        {visible && isCalibrated && gridLines.map((l, i) => (
          <g key={i}>
            <line
              x1={l.x1} y1={l.y1} x2={l.x2} y2={l.y2}
              stroke="#000"
              strokeWidth={l.isNet ? 6 : 4}
              strokeOpacity={0.75}
            />
            <line
              x1={l.x1} y1={l.y1} x2={l.x2} y2={l.y2}
              stroke={l.isNet ? COLORS.net : COLORS.grid}
              strokeWidth={l.isNet ? 2.5 : 1.5}
              strokeOpacity={1.0}
            />
          </g>
        ))}

        {/* ─── キャリブレーション点 ────────────────────────────── */}
        {(visible || calibrating) && points.map((pt, i) => (
          <g key={i}>
            <circle
              cx={pt.x * w} cy={pt.y * h} r={6}
              fill={COLORS.point} fillOpacity={0.85}
              stroke="#000" strokeWidth={1.5}
              style={{ cursor: calibrating ? 'default' : 'grab', pointerEvents: calibrating ? 'none' : 'all' }}
              onPointerDown={(e) => handlePointPointerDown(e, i)}
            />
            <text
              x={pt.x * w + 9} y={pt.y * h + 4}
              fontSize={10} fill={COLORS.text}
              stroke="#000" strokeWidth={2.5} paintOrder="stroke"
              style={{ pointerEvents: 'none', userSelect: 'none' }}
            >
              {i + 1}
            </text>
          </g>
        ))}

        {/* ─── 次の点のプレビュー表示 ──────────────────────────── */}
        {calibrating && nextPointIdx !== null && nextPointIdx < TOTAL_POINTS && (
          <text
            x={w * 0.5} y={h * 0.08}
            textAnchor="middle" fontSize={13}
            fill={COLORS.nextPoint}
            stroke="#000" strokeWidth={3} paintOrder="stroke"
            style={{ pointerEvents: 'none', userSelect: 'none' }}
          >
            {t('auto.CourtGridOverlay.click_point', { n: nextPointIdx + 1, total: TOTAL_POINTS, label: t(POINT_LABEL_KEYS[nextPointIdx]) })}
          </text>
        )}
      </svg>

      {/* ─── グリッド線再作成 + キャリブ保存状態（左上）────────── */}
      {visible && isCalibrated && !calibrating && (
        <div className="absolute top-1 left-1 flex items-center gap-1" style={{ pointerEvents: 'all' }}>
          <button
            onClick={startCalibration}
            className="flex items-center gap-1 bg-black/50 rounded px-1.5 py-0.5 hover:bg-black/70 transition-colors"
            style={{ color: '#ffffff', fontSize: 9, fontWeight: 500, lineHeight: 1.4 }}
          >
            {t('auto.CourtGridOverlay.recreate_grid')}
          </button>
          {/* キャリブレーション保存状態インジケーター */}
          {calibSource === 'backend' && (
            <span
              className="flex items-center gap-0.5 bg-green-900/70 rounded px-1 py-0.5"
              style={{ color: '#86efac', fontSize: 8, lineHeight: 1.4, pointerEvents: 'none' }}
            >
              {t('auto.CourtGridOverlay.db_saved')}
            </span>
          )}
          {calibSource === 'local' && (
            <button
              onClick={() => postToBackend(points)}
              className="flex items-center gap-0.5 bg-yellow-900/70 rounded px-1 py-0.5 hover:bg-yellow-800/80 transition-colors"
              style={{ color: '#fde68a', fontSize: 8, lineHeight: 1.4 }}
              title={t('auto.CourtGridOverlay.k3')}
            >
              {t('auto.CourtGridOverlay.local_only_sync')}
            </button>
          )}
        </div>
      )}

      {/* ─── 保存中トースト ─────────────────────────── */}
      {saving && (
        <div
          className="absolute top-2 left-1/2 -translate-x-1/2 px-3 py-1 rounded text-xs bg-blue-900/90 border border-blue-500 text-blue-100"
          style={{ pointerEvents: 'none', zIndex: 30 }}
        >
          {t('auto.CourtGridOverlay.db_saving')}
        </div>
      )}

      {/* ─── 保存完了トースト（6秒） ─────────────────────────── */}
      {savedNotice && (
        <div
          className="absolute top-2 left-1/2 -translate-x-1/2 px-3 py-1 rounded text-xs bg-gray-900/90 border border-gray-600 text-gray-200"
          style={{ pointerEvents: 'none', zIndex: 30 }}
        >
          {t('auto.CourtGridOverlay.db_save_done')}
        </div>
      )}

      {/* ─── 保存エラートースト（12秒、コピー可能） ───────────────────
          PlayerTrackingOverlay と同じ pattern: 本文 select-text +
          コピーボタンで原文を確実に持ち出せるようにする。zIndex は
          ROI overlay (30) と calibrating 中の自身 (35) より上に置く。 */}
      {saveError && (
        <div
          className="absolute top-2 left-1/2 -translate-x-1/2 px-2 py-1.5 rounded bg-red-900/95 border border-red-500 max-w-md flex items-start gap-2"
          style={{ pointerEvents: 'auto', zIndex: 40 }}
        >
          <pre
            className="text-[11px] font-mono whitespace-pre-wrap break-all text-left select-text overflow-auto"
            style={{ color: '#fca5a5', maxHeight: '40vh', userSelect: 'text', margin: 0 }}
          >{saveError}</pre>
          <button
            type="button"
            className="shrink-0 text-[10px] bg-red-800 hover:bg-red-700 active:bg-red-900 rounded px-2 py-1"
            style={{ color: '#ffffff' }}
            onClick={() => {
              try { navigator.clipboard.writeText(saveError) } catch { /* ignore */ }
            }}
            title={t('auto.CourtGridOverlay.copy_error', { defaultValue: 'エラーをコピー' })}
          >
            {t('auto.CourtGridOverlay.copy', { defaultValue: 'コピー' })}
          </button>
          <button
            type="button"
            className="shrink-0 text-[10px] bg-red-800 hover:bg-red-700 active:bg-red-900 rounded px-2 py-1"
            style={{ color: '#ffffff' }}
            onClick={() => setSaveError(null)}
            title={t('auto.CourtGridOverlay.dismiss', { defaultValue: '閉じる' })}
          >
            <MIcon name="close" size={12} />
          </button>
        </div>
      )}

      {/* ─── 未キャリブレーション時の案内 ───────────────────────── */}
      {visible && !isCalibrated && !calibrating && (
        <div
          className="absolute inset-0 flex items-center justify-center"
          style={{ pointerEvents: 'all' }}
        >
          <button
            onClick={startCalibration}
            className="flex flex-col items-center gap-2 px-6 py-4 rounded-lg bg-gray-900/80 border border-gray-600 hover:bg-gray-800/90 text-sm"
            style={{ color: '#e5e7eb' }}
          >
            <MIcon name="mouse" size={20} className="text-cyan-400" />
            <span>{t('auto.CourtGridOverlay.k1')}</span>
            <span className="text-xs" style={{ color: '#9ca3af' }}>{t('auto.CourtGridOverlay.k2')}</span>
          </button>
        </div>
      )}
    </div>

    {/* ─── キャンセルボタン ─────────────────────────────────────────
        zIndex:20 コンテナの外に出して zIndex:40 に配置。
        ROI オーバーレイ (zIndex:30) に隠れず常にクリック可能。
        位置は上端中央 — コート点と重ならない安全エリア。
    ───────────────────────────────────────────────────────────── */}
    {calibrating && (
      <div
        className="absolute top-2 left-1/2 -translate-x-1/2"
        style={{ zIndex: 40, pointerEvents: 'all' }}
      >
        <button
          onClick={() => {
            setCalibrating(false)
            if (prevPtsRef.current.length === TOTAL_POINTS) {
              savePts(prevPtsRef.current)
            } else {
              setPoints([])
            }
          }}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium
                     bg-red-700 hover:bg-red-600 border border-red-500 shadow-lg"
          style={{ color: '#ffffff' }}
        >
          <MIcon name="close" size={12} style={{ color: '#ffffff' }} />
          {t('auto.CourtGridOverlay.cancel')}
        </button>
      </div>
    )}
    </>
  )
}
