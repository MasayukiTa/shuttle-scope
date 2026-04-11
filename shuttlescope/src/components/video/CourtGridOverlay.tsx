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
import { RotateCcw, MousePointer2 } from 'lucide-react'

// ─── 型 ─────────────────────────────────────────────────────────────────────

type Pt = { x: number; y: number }  // コンテナ基準の正規化座標 [0, 1]

interface CourtGridOverlayProps {
  matchId: string
  containerRef: RefObject<HTMLDivElement>
  /** グリッド全体の表示/非表示 */
  visible: boolean
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
  grid: '#ffffff',
  net: '#ff9900',
  point: '#ffff00',
  nextPoint: '#00ff88',
  text: '#ffffff',
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

export function CourtGridOverlay({ matchId, containerRef, visible }: CourtGridOverlayProps) {
  const [points, setPoints] = useState<Pt[]>([])          // 設定済み点（最大6個）
  const [calibrating, setCalibrating] = useState(false)   // キャリブレーションモード
  const [draggingIdx, setDraggingIdx] = useState<number | null>(null)
  const [containerSize, setContainerSize] = useState({ w: 1, h: 1 })
  const svgRef = useRef<SVGSVGElement>(null)

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
    fetch(`/api/matches/${matchId}/court_calibration`)
      .then((r) => r.ok ? r.json() : Promise.reject(r.status))
      .then((res) => {
        if (cancelled) return
        const raw: [number, number][] = res?.data?.points ?? []
        if (raw.length === TOTAL_POINTS) {
          const pts = raw.map(([x, y]) => ({ x, y }))
          setPoints(pts)
          try { localStorage.setItem(STORAGE_KEY(matchId), JSON.stringify(pts)) } catch { /* ignore */ }
        }
      })
      .catch(() => {
        // バックエンド未設定 → localStorage フォールバック
        if (cancelled) return
        try {
          const saved = localStorage.getItem(STORAGE_KEY(matchId))
          if (saved) setPoints(JSON.parse(saved))
        } catch { /* ignore */ }
      })
    return () => { cancelled = true }
  }, [matchId])

  const savePts = useCallback((pts: Pt[]) => {
    setPoints(pts)
    try { localStorage.setItem(STORAGE_KEY(matchId), JSON.stringify(pts)) } catch { /* ignore */ }
    // 6点揃ったらバックエンドへ保存
    if (pts.length === TOTAL_POINTS) {
      fetch(`/api/matches/${matchId}/court_calibration`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          points: pts.map((p) => ({ x: p.x, y: p.y })),
          container_width:  containerSize.w,
          container_height: containerSize.h,
        }),
      }).catch((err) => console.warn('[CourtGrid] backend save failed:', err))
    }
  }, [matchId, containerSize])

  // ─── キャリブレーション操作 ────────────────────────────────────────────

  const startCalibration = useCallback(() => {
    setPoints([])
    localStorage.removeItem(STORAGE_KEY(matchId))
    setCalibrating(true)
  }, [matchId])

  const getSVGPoint = useCallback((e: React.PointerEvent<SVGSVGElement>): Pt => {
    const rect = svgRef.current!.getBoundingClientRect()
    return {
      x: (e.clientX - rect.left) / rect.width,
      y: (e.clientY - rect.top) / rect.height,
    }
  }, [])

  const handleSVGPointerDown = useCallback((e: React.PointerEvent<SVGSVGElement>) => {
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

    // 下サイドの4隅: NL, NR, BR, BL (外周ラインは上サイドと共有のため省略)
    const botLines = halfGridLines(NL, NR, BR, BL, w, h, false)
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
          cursor: calibrating ? 'crosshair' : (draggingIdx !== null ? 'grabbing' : 'default'),
        }}
        onPointerDown={handleSVGPointerDown}
        onPointerMove={handleSVGPointerMove}
        onPointerUp={handleSVGPointerUp}
      >
        {/* ─── グリッドライン ───────────────────────────────────── */}
        {visible && isCalibrated && gridLines.map((l, i) => (
          <line
            key={i}
            x1={l.x1} y1={l.y1} x2={l.x2} y2={l.y2}
            stroke={l.isNet ? COLORS.net : COLORS.grid}
            strokeWidth={l.isNet ? 2.5 : 1.5}
            strokeOpacity={l.isNet ? 1.0 : 0.85}
          />
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

      {/* ─── キャリブレーション UI ボタン ──────────────────────── */}
      {visible && (
        <div
          className="absolute bottom-2 right-2 flex gap-1"
          style={{ pointerEvents: 'all' }}
        >
          {calibrating ? (
            <button
              onClick={() => { setCalibrating(false); setPoints([]) }}
              className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-red-800/80 hover:bg-red-700 text-white border border-red-600"
            >
              キャンセル
            </button>
          ) : (
            <button
              onClick={startCalibration}
              className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-gray-900/80 hover:bg-gray-800 text-gray-200 border border-gray-600"
              title="コート点を再設定（カメラ切替後など）"
            >
              <RotateCcw size={11} />
              再キャリブレーション
            </button>
          )}
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
            className="flex flex-col items-center gap-2 px-6 py-4 rounded-lg bg-gray-900/80 border border-gray-600 text-gray-200 hover:bg-gray-800/90 text-sm"
          >
            <MousePointer2 size={20} className="text-cyan-400" />
            <span>コートグリッドを設定</span>
            <span className="text-xs text-gray-400">4コーナーとネット支柱2点をクリックして設定</span>
          </button>
        </div>
      )}
    </div>
  )
}
