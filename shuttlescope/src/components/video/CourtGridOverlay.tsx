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
import { MousePointer2 } from 'lucide-react'
import { apiGet, apiPost } from '@/api/client'
import { useTranslation } from 'react-i18next'

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

const POINT_LABELS = [
  'コート左上', 'コート右上',
  'コート右下', 'コート左下',
  'ネット左支柱', 'ネット右支柱',
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
  const endR = includeOuter ? GRID_ROWS : GRID_ROWS - 1
  const startC = includeOuter ? 0 : 1
  const endC = includeOuter ? GRID_COLS : GRID_COLS - 1

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

  const postToBackend = useCallback((pts: Pt[]) => {
    setSaving(true)
    // apiPost が http://localhost:8765/api を絶対 URL で叩く（Electron file:// 対応）
    apiPost(`/matches/${matchId}/court_calibration`, {
      points: pts.map((p) => ({ x: p.x, y: p.y })),
      container_width:  containerSize.w,
      container_height: containerSize.h,
    })
      .then(() => {
        setSaveError(null)
        setCalibSource('backend')
        setSavedNotice(true)
        setTimeout(() => setSavedNotice(false), 6000)
        onCalibrationSaved?.()
      })
      .catch((err: unknown) => {
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
        setTimeout(() => setSaveError(null), 8000)
      })
      .finally(() => setSaving(false))
  }, [matchId, containerSize, onCalibrationSaved])

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
      style={{ zIndex: 20 }}
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
            点{nextPointIdx + 1}/{TOTAL_POINTS}：{POINT_LABELS[nextPointIdx]} をクリック
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
            グリッド線再作成
          </button>
          {/* キャリブレーション保存状態インジケーター */}
          {calibSource === 'backend' && (
            <span
              className="flex items-center gap-0.5 bg-green-900/70 rounded px-1 py-0.5"
              style={{ color: '#86efac', fontSize: 8, lineHeight: 1.4, pointerEvents: 'none' }}
            >
              ✓ DB保存済
            </span>
          )}
          {calibSource === 'local' && (
            <button
              onClick={() => postToBackend(points)}
              className="flex items-center gap-0.5 bg-yellow-900/70 rounded px-1 py-0.5 hover:bg-yellow-800/80 transition-colors"
              style={{ color: '#fde68a', fontSize: 8, lineHeight: 1.4 }}
              title={t('auto.CourtGridOverlay.k3')}
            >
              ⚠ ローカルのみ → 同期
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
          💾 DBへ保存中...
        </div>
      )}

      {/* ─── 保存完了トースト（6秒） ─────────────────────────── */}
      {savedNotice && (
        <div
          className="absolute top-2 left-1/2 -translate-x-1/2 px-3 py-1 rounded text-xs bg-gray-900/90 border border-gray-600 text-gray-200"
          style={{ pointerEvents: 'none', zIndex: 30 }}
        >
          ✓ DB保存完了
        </div>
      )}

      {/* ─── 保存エラートースト（8秒） ─────────────────────────── */}
      {saveError && (
        <div
          className="absolute top-2 left-1/2 -translate-x-1/2 px-3 py-1 rounded text-xs bg-red-900/90 border border-red-500 text-red-200 max-w-xs text-center"
          style={{ pointerEvents: 'none', zIndex: 30 }}
        >
          ✗ {saveError}
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
            <MousePointer2 size={20} className="text-cyan-400" />
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
          <span style={{ color: '#ffffff', fontSize: 12, lineHeight: 1 }}>✕</span>
          キャンセル
        </button>
      </div>
    )}
    </>
  )
}
