/**
 * ShuttleTrackOverlay
 *
 * TrackNet シャトル軌跡をビデオ上にキャンバスオーバーレイで描画する。
 * プレイヤーオーバーレイとは独立したトグルで表示/非表示を切り替えられる。
 *
 * データソース: GET /api/tracknet/shuttle_track/{match_id}
 *
 * 描画内容:
 *   - 現在位置に大きなドット（信頼度で不透明度変化）
 *   - 直近 TRAIL_LEN 点の軌跡（フェードアウト）
 *   - ゾーンラベル（例: NL / BL / FR）
 *   - "research" バッジ（右上）
 *
 * Props:
 *   frames     — TrackNet フレーム一覧
 *   currentSec — 現在の動画再生位置（秒）
 *   videoWidth / videoHeight — 描画領域のピクセルサイズ
 *   visible    — オーバーレイ表示/非表示
 */
import { useEffect, useRef, useMemo } from 'react'

export interface ShuttleFrame {
  timestamp_sec: number
  zone: string | null
  confidence: number
  x_norm: number | null
  y_norm: number | null
}

interface Props {
  frames: ShuttleFrame[]
  currentSec: number
  videoWidth: number
  videoHeight: number
  visible: boolean
}

/** 軌跡として描画する過去フレーム数 */
const TRAIL_LEN = 8

/** 現在時刻に最も近いフレームのインデックスを返す（±2s 以内） */
function findNearestIndex(frames: ShuttleFrame[], sec: number): number {
  if (!frames.length) return -1
  let best = -1
  let bestGap = Infinity
  for (let i = 0; i < frames.length; i++) {
    const gap = Math.abs(frames[i].timestamp_sec - sec)
    if (gap < bestGap) {
      bestGap = gap
      best = i
    }
  }
  return bestGap <= 2.0 ? best : -1
}

export function ShuttleTrackOverlay({
  frames,
  currentSec,
  videoWidth,
  videoHeight,
  visible,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  const nearestIdx = useMemo(
    () => findNearestIndex(frames, currentSec),
    [frames, currentSec],
  )

  /** 現在フレームより前の TRAIL_LEN 点（軌跡） */
  const trailFrames = useMemo(() => {
    if (nearestIdx < 0) return []
    const start = Math.max(0, nearestIdx - TRAIL_LEN + 1)
    return frames.slice(start, nearestIdx + 1)
  }, [frames, nearestIdx])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    ctx.clearRect(0, 0, canvas.width, canvas.height)

    if (!visible || trailFrames.length === 0) return

    const w = canvas.width
    const h = canvas.height
    const trailLen = trailFrames.length

    // 軌跡を古い順に描画（フェードアウト）
    for (let i = 0; i < trailLen; i++) {
      const f = trailFrames[i]
      if (f.x_norm == null || f.y_norm == null) continue

      const cx = f.x_norm * w
      const cy = f.y_norm * h
      const isCurrent = i === trailLen - 1

      // 古いほど小さく・薄く
      const ageFactor = (i + 1) / trailLen        // 0..1, 1=現在
      const alpha = ageFactor * (isCurrent ? f.confidence : f.confidence * 0.5)
      const radius = isCurrent ? 6 : 2 + ageFactor * 2

      ctx.beginPath()
      ctx.arc(cx, cy, radius, 0, Math.PI * 2)
      ctx.fillStyle = isCurrent ? '#facc15' : '#fde68a'   // yellow-400 / amber-200
      ctx.globalAlpha = Math.min(alpha, 1)
      ctx.fill()
      ctx.globalAlpha = 1

      // 現在点のアウトライン
      if (isCurrent) {
        ctx.beginPath()
        ctx.arc(cx, cy, radius + 2, 0, Math.PI * 2)
        ctx.strokeStyle = '#f59e0b'  // amber-500
        ctx.lineWidth = 1.5
        ctx.globalAlpha = 0.7
        ctx.stroke()
        ctx.globalAlpha = 1

        // ゾーンラベル
        const zone = f.zone ?? '?'
        const conf = Math.round(f.confidence * 100)
        const text = `${zone} ${conf}%`
        ctx.font = 'bold 11px system-ui, sans-serif'
        const metrics = ctx.measureText(text)
        const padX = 4
        const padY = 2
        const labelH = 15
        const labelW = metrics.width + padX * 2
        const labelX = cx - labelW / 2
        const labelY = cy > labelH + 10 ? cy - radius - labelH - 4 : cy + radius + 4

        ctx.fillStyle = '#000'
        ctx.globalAlpha = 0.65
        ctx.beginPath()
        ctx.roundRect(labelX, labelY, labelW, labelH, 3)
        ctx.fill()
        ctx.globalAlpha = 1

        ctx.fillStyle = '#facc15'
        ctx.fillText(text, labelX + padX, labelY + labelH - padY - 1)
      }
    }

    // 軌跡ライン
    if (trailLen >= 2) {
      ctx.beginPath()
      for (let i = 0; i < trailLen; i++) {
        const f = trailFrames[i]
        if (f.x_norm == null || f.y_norm == null) continue
        const cx = f.x_norm * w
        const cy = f.y_norm * h
        if (i === 0) ctx.moveTo(cx, cy)
        else ctx.lineTo(cx, cy)
      }
      ctx.strokeStyle = '#fbbf24'  // amber-400
      ctx.lineWidth = 1.5
      ctx.globalAlpha = 0.45
      ctx.stroke()
      ctx.globalAlpha = 1
    }
  }, [trailFrames, visible, videoWidth, videoHeight])

  if (!visible) return null

  return (
    <div
      className="absolute inset-0 pointer-events-none"
      style={{ width: videoWidth, height: videoHeight }}
    >
      <canvas
        ref={canvasRef}
        width={videoWidth}
        height={videoHeight}
        className="absolute inset-0"
        style={{ width: videoWidth, height: videoHeight }}
      />
      {/* research badge */}
      <div className="absolute top-1 left-1 flex items-center gap-1 bg-black/50 rounded px-1.5 py-0.5">
        <span className="text-yellow-400 text-[9px] font-bold uppercase tracking-wide">
          shuttle track
        </span>
      </div>
      {/* no-data hint */}
      {nearestIdx < 0 && frames.length > 0 && (
        <div className="absolute bottom-1 left-1/2 -translate-x-1/2 text-[10px] text-gray-400 bg-black/50 rounded px-2 py-0.5">
          この時刻のシャトルデータなし
        </div>
      )}
    </div>
  )
}
