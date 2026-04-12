/**
 * RoiRectOverlay — ビデオ上でドラッグしてTrackNet/YOLO処理領域（ROI）を指定する。
 *
 * 使い方:
 *   - editing=true: ドラッグで矩形を描画
 *   - editing=false: 確定済み領域を表示 + 4コーナーをドラッグして形状調整
 *   - 右上の × で矩形をリセット
 *
 * zIndex: 30 — CourtGridOverlay(20) より上に常に配置。
 * 編集モード以外は pointerEvents:none — CourtGrid 操作を邪魔しない。
 * コーナードラッグは window イベントで追跡 — z-index 競合を回避。
 */
import { useRef, useState, useCallback, useEffect, type RefObject } from 'react'
import { X } from 'lucide-react'

type Pt = { x: number; y: number }

/** 正規化座標 (0-1) の領域。バックエンドは x,y,w,h のみ使用。 */
export interface RoiRect {
  x: number  // バウンディングボックス 左辺 (min x)
  y: number  // バウンディングボックス 上辺 (min y)
  w: number  // バウンディングボックス 幅
  h: number  // バウンディングボックス 高さ
  /** 4コーナー [TL, TR, BR, BL] — 台形など非矩形指定用。未指定時は x,y,w,h から矩形補完 */
  corners?: readonly [Pt, Pt, Pt, Pt]
}

interface Props {
  value: RoiRect | null
  onChange: (rect: RoiRect | null) => void
  /** true のとき矩形を描画できる（編集モード） */
  editing: boolean
  containerRef: RefObject<HTMLElement | null>
}

// ── ユーティリティ ─────────────────────────────────────────────────────────────

function clamp01(v: number) { return Math.max(0, Math.min(1, v)) }

function rectToCorners(r: RoiRect): [Pt, Pt, Pt, Pt] {
  if (r.corners) return [...r.corners] as [Pt, Pt, Pt, Pt]
  return [
    { x: r.x,       y: r.y       },  // TL
    { x: r.x + r.w, y: r.y       },  // TR
    { x: r.x + r.w, y: r.y + r.h },  // BR
    { x: r.x,       y: r.y + r.h },  // BL
  ]
}

function cornersToRect(corners: [Pt, Pt, Pt, Pt]): RoiRect {
  const xs = corners.map((c) => c.x)
  const ys = corners.map((c) => c.y)
  const x = Math.min(...xs)
  const y = Math.min(...ys)
  const w = Math.max(...xs) - x
  const h = Math.max(...ys) - y
  return { x, y, w, h, corners }
}

// ── コンポーネント ─────────────────────────────────────────────────────────────

export function RoiRectOverlay({ value, onChange, editing, containerRef }: Props) {
  // コンテナの実ピクセルサイズ（SVG polygon の座標計算用）
  const [size, setSize] = useState({ w: 1, h: 1 })
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const update = () => setSize({ w: el.clientWidth || 1, h: el.clientHeight || 1 })
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [containerRef])

  // ── 新規ドラッグ描画 (editing=true) ──────────────────────────────────────────
  const [draft, setDraft] = useState<{ x: number; y: number; w: number; h: number } | null>(null)
  const startPt = useRef<Pt | null>(null)

  const toNorm = useCallback((e: { clientX: number; clientY: number }) => {
    const el = containerRef.current
    if (!el) return null
    const rect = el.getBoundingClientRect()
    return {
      x: clamp01((e.clientX - rect.left) / rect.width),
      y: clamp01((e.clientY - rect.top)  / rect.height),
    }
  }, [containerRef])

  const onDrawMouseDown = useCallback((e: React.MouseEvent) => {
    if (!editing) return
    e.preventDefault()
    const pt = toNorm(e)
    if (!pt) return
    startPt.current = pt
    setDraft({ x: pt.x, y: pt.y, w: 0, h: 0 })
  }, [editing, toNorm])

  const onDrawMouseMove = useCallback((e: React.MouseEvent) => {
    if (!editing || !startPt.current) return
    const pt = toNorm(e)
    if (!pt) return
    const x = Math.min(startPt.current.x, pt.x)
    const y = Math.min(startPt.current.y, pt.y)
    const w = Math.abs(pt.x - startPt.current.x)
    const h = Math.abs(pt.y - startPt.current.y)
    setDraft({ x, y, w, h })
  }, [editing, toNorm])

  const onDrawMouseUp = useCallback(() => {
    if (!editing || !draft) return
    if (draft.w > 0.05 && draft.h > 0.05) {
      const corners: [Pt, Pt, Pt, Pt] = [
        { x: draft.x,         y: draft.y         },  // TL
        { x: draft.x + draft.w, y: draft.y         },  // TR
        { x: draft.x + draft.w, y: draft.y + draft.h },  // BR
        { x: draft.x,         y: draft.y + draft.h },  // BL
      ]
      onChange({ ...draft, corners })
    }
    setDraft(null)
    startPt.current = null
  }, [editing, draft, onChange])

  // ── コーナードラッグ (editing=false) ──────────────────────────────────────────
  const [draggingCorner, setDraggingCorner] = useState<number | null>(null)

  // コーナードラッグ中は window に mousemove/mouseup をアタッチ
  useEffect(() => {
    if (draggingCorner === null) return

    const handleMove = (e: MouseEvent) => {
      const pt = toNorm(e)
      if (!pt || !value) return
      const corners = rectToCorners(value)
      corners[draggingCorner] = pt
      onChange(cornersToRect(corners))
    }

    const handleUp = () => setDraggingCorner(null)

    window.addEventListener('mousemove', handleMove)
    window.addEventListener('mouseup', handleUp)
    return () => {
      window.removeEventListener('mousemove', handleMove)
      window.removeEventListener('mouseup', handleUp)
    }
  }, [draggingCorner, value, onChange, toNorm])

  // ── SVG polygon 用座標 ────────────────────────────────────────────────────────
  const corners = value ? rectToCorners(value) : null
  const svgPolyPoints = corners
    ? corners.map((c) => `${c.x * size.w},${c.y * size.h}`).join(' ')
    : ''

  return (
    <div
      className="absolute inset-0"
      style={{
        // CourtGridOverlay (zIndex:20) より常に上
        zIndex: 30,
        cursor: editing ? 'crosshair' : (draggingCorner !== null ? 'grabbing' : 'default'),
        // 編集中のみ pointer-events:auto（CourtGrid の操作を邪魔しない）
        pointerEvents: editing ? 'auto' : 'none',
      }}
      onMouseDown={onDrawMouseDown}
      onMouseMove={onDrawMouseMove}
      onMouseUp={onDrawMouseUp}
      onMouseLeave={onDrawMouseUp}
    >
      {/* ドラッグ中の仮矩形 */}
      {draft && (
        <div
          className="absolute pointer-events-none"
          style={{
            left:   `${draft.x * 100}%`,
            top:    `${draft.y * 100}%`,
            width:  `${draft.w * 100}%`,
            height: `${draft.h * 100}%`,
            border: '2px dashed #f59e0b',
            background: 'rgba(245,158,11,0.07)',
          }}
        />
      )}

      {/* 確定済みROI: SVGポリゴン + コーナーハンドル */}
      {!editing && value && corners && (
        <>
          {/* SVG polygon — 台形など非矩形を正確に描画 */}
          <svg
            className="absolute inset-0 overflow-visible"
            style={{ width: '100%', height: '100%', pointerEvents: 'none' }}
          >
            <polygon
              points={svgPolyPoints}
              fill="rgba(245,158,11,0.08)"
              stroke="#f59e0b"
              strokeWidth={1.5}
            />
          </svg>

          {/* ラベル（TL コーナー基準・白文字） */}
          <div
            className="absolute text-[10px] bg-amber-500 text-white px-1 leading-4 rounded-br select-none"
            style={{
              left: `${corners[0].x * 100}%`,
              top:  `${corners[0].y * 100}%`,
              pointerEvents: 'none',
              zIndex: 31,
            }}
          >
            解析領域
          </div>

          {/* × ボタン（TR コーナー右上・白文字） */}
          <button
            className="absolute bg-amber-500 text-white p-0.5 rounded-bl hover:bg-amber-400 transition-colors"
            style={{
              left:      `${corners[1].x * 100}%`,
              top:       `${corners[1].y * 100}%`,
              transform: 'translate(-100%, 0)',
              pointerEvents: 'auto',
              zIndex: 31,
            }}
            onClick={(e) => { e.stopPropagation(); onChange(null) }}
            title="解析領域をリセット"
          >
            <X size={10} />
          </button>

          {/* 4コーナーハンドル */}
          {corners.map((c, i) => (
            <div
              key={i}
              className="absolute w-3.5 h-3.5 rounded-full bg-amber-400 border-2 border-white shadow"
              style={{
                left:      `${c.x * 100}%`,
                top:       `${c.y * 100}%`,
                transform: 'translate(-50%, -50%)',
                cursor:    'grab',
                pointerEvents: 'auto',
                zIndex: 31,
              }}
              onMouseDown={(e) => {
                e.stopPropagation()
                e.preventDefault()
                setDraggingCorner(i)
              }}
              title={['左上', '右上', '右下', '左下'][i]}
            />
          ))}
        </>
      )}

      {/* 編集中ヒント（まだドラッグしていないとき） */}
      {editing && !draft && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <span
            className="bg-black/70 text-xs px-3 py-1.5 rounded-full"
            style={{ color: '#ffffff', fontWeight: 500 }}
          >
            ドラッグして解析領域を指定
          </span>
        </div>
      )}
    </div>
  )
}
