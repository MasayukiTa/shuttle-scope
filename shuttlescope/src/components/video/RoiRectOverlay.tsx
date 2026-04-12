/**
 * RoiRectOverlay — ビデオ上でドラッグしてTrackNet/YOLO処理領域（ROI）を指定する。
 *
 * 使い方:
 *   - editing=true: ドラッグで矩形を描画
 *   - editing=false: 指定済み矩形を薄いガイド枠として表示
 *   - 右上の × で矩形をリセット
 */
import { useRef, useState, useCallback, type RefObject } from 'react'
import { X } from 'lucide-react'

/** 正規化座標 (0-1) の矩形 */
export interface RoiRect {
  x: number  // 左辺
  y: number  // 上辺
  w: number  // 幅
  h: number  // 高さ
}

interface Props {
  value: RoiRect | null
  onChange: (rect: RoiRect | null) => void
  /** true のとき矩形を描画できる（編集モード） */
  editing: boolean
  containerRef: RefObject<HTMLElement | null>
}

function clamp01(v: number) { return Math.max(0, Math.min(1, v)) }

export function RoiRectOverlay({ value, onChange, editing, containerRef }: Props) {
  const [draft, setDraft] = useState<RoiRect | null>(null)
  const startPt = useRef<{ x: number; y: number } | null>(null)

  const toNorm = useCallback((e: React.MouseEvent) => {
    const el = containerRef.current
    if (!el) return null
    const rect = el.getBoundingClientRect()
    return {
      x: clamp01((e.clientX - rect.left) / rect.width),
      y: clamp01((e.clientY - rect.top)  / rect.height),
    }
  }, [containerRef])

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    if (!editing) return
    e.preventDefault()
    const pt = toNorm(e)
    if (!pt) return
    startPt.current = pt
    setDraft({ x: pt.x, y: pt.y, w: 0, h: 0 })
  }, [editing, toNorm])

  const onMouseMove = useCallback((e: React.MouseEvent) => {
    if (!editing || !startPt.current) return
    const pt = toNorm(e)
    if (!pt) return
    const x = Math.min(startPt.current.x, pt.x)
    const y = Math.min(startPt.current.y, pt.y)
    const w = Math.abs(pt.x - startPt.current.x)
    const h = Math.abs(pt.y - startPt.current.y)
    setDraft({ x, y, w, h })
  }, [editing, toNorm])

  const onMouseUp = useCallback((e: React.MouseEvent) => {
    if (!editing || !draft) return
    const pt = toNorm(e)
    if (!pt) return
    // 最小サイズ (5%) 未満は無視
    if (draft.w > 0.05 && draft.h > 0.05) {
      onChange(draft)
    }
    setDraft(null)
    startPt.current = null
  }, [editing, draft, toNorm, onChange])

  const display = draft ?? value

  return (
    <div
      className="absolute inset-0"
      style={{ cursor: editing ? 'crosshair' : 'default' }}
      onMouseDown={onMouseDown}
      onMouseMove={onMouseMove}
      onMouseUp={onMouseUp}
      onMouseLeave={onMouseUp}
    >
      {display && (
        <div
          className="absolute"
          style={{
            left:   `${display.x * 100}%`,
            top:    `${display.y * 100}%`,
            width:  `${display.w * 100}%`,
            height: `${display.h * 100}%`,
            border: `2px ${editing ? 'dashed' : 'solid'} #f59e0b`,
            background: 'rgba(245,158,11,0.07)',
            pointerEvents: editing ? 'none' : 'auto',
          }}
        >
          {/* ラベル */}
          <span
            className="absolute top-0 left-0 text-[10px] bg-amber-500 text-white px-1 py-0 leading-4 rounded-br select-none"
          >
            解析領域
          </span>
          {/* 確定済みのときだけ × ボタン */}
          {!editing && value && (
            <button
              className="absolute top-0 right-0 bg-amber-500 text-white p-0.5 rounded-bl hover:bg-amber-400"
              onClick={(e) => { e.stopPropagation(); onChange(null) }}
              title="解析領域をリセット"
            >
              <X size={10} />
            </button>
          )}
        </div>
      )}
      {/* 編集中のヒント */}
      {editing && !draft && !value && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <span className="bg-black/60 text-amber-300 text-xs px-3 py-1.5 rounded-full">
            ドラッグして解析領域を指定
          </span>
        </div>
      )}
    </div>
  )
}
