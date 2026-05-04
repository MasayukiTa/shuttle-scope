/**
 * PlayerPositionOverlay
 *
 * YOLO プレイヤー検出結果をビデオ上にキャンバスオーバーレイで描画する。
 * ラベルは「assisted / research」扱いであることをバッジで明示する。
 *
 * Props:
 *   frames     — YOLO バッチ結果 (GET /api/yolo/results/{match_id}/frames)
 *   currentSec — 現在の動画再生位置（秒）
 *   videoWidth / videoHeight — 実際に描画されているビデオ要素の表示サイズ（px）
 *   visible    — オーバーレイ表示/非表示
 */
import { useEffect, useRef, useMemo } from 'react'
import { useTranslation } from 'react-i18next'

interface PlayerDetection {
  label: string           // "player_a" | "player_b" | "player_other"
  confidence: number
  bbox: [number, number, number, number]  // x1n, y1n, x2n, y2n (normalized)
  centroid: [number, number]
  court_side: string      // "left" | "right"
  depth_band: string      // "front" | "mid" | "back"
}

interface YoloFrame {
  frame_idx: number
  timestamp_sec: number
  players: PlayerDetection[]
}

interface Props {
  frames: YoloFrame[]
  currentSec: number
  videoWidth: number
  videoHeight: number
  visible: boolean
}

/** 現在時刻に最も近いフレームを返す（±1.5s 以内） */
function findNearestFrame(frames: YoloFrame[], sec: number): YoloFrame | null {
  if (!frames.length) return null
  let best: YoloFrame | null = null
  let bestGap = Infinity
  for (const f of frames) {
    const gap = Math.abs(f.timestamp_sec - sec)
    if (gap < bestGap) {
      bestGap = gap
      best = f
    }
  }
  return bestGap <= 1.5 ? best : null
}

const PLAYER_COLORS: Record<string, string> = {
  player_a: '#3b82f6',    // blue-500
  player_b: '#f59e0b',    // amber-500
  player_other: '#6b7280', // gray-500
}

const DEPTH_LABELS: Record<string, string> = {
  front: '前',
  mid: '中',
  back: '後',
}

export function PlayerPositionOverlay({
  frames,
  currentSec,
  videoWidth,
  videoHeight,
  visible,
}: Props) {
  const { t } = useTranslation()
  const canvasRef = useRef<HTMLCanvasElement>(null)

  const nearestFrame = useMemo(
    () => findNearestFrame(frames, currentSec),
    [frames, currentSec],
  )

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    // 高DPIモニタ対応: 物理ピクセル解像度でCanvasを確保してからスケーリング
    const dpr = window.devicePixelRatio || 1
    canvas.width = videoWidth * dpr
    canvas.height = videoHeight * dpr

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    ctx.scale(dpr, dpr)
    ctx.clearRect(0, 0, videoWidth, videoHeight)

    if (!visible || !nearestFrame) return

    const w = videoWidth
    const h = videoHeight

    for (const player of nearestFrame.players) {
      const color = PLAYER_COLORS[player.label] ?? '#6b7280'
      const [x1n, y1n, x2n, y2n] = player.bbox
      const x1 = x1n * w
      const y1 = y1n * h
      const bw = (x2n - x1n) * w
      const bh = (y2n - y1n) * h

      // bbox
      ctx.strokeStyle = color
      ctx.lineWidth = 2
      ctx.globalAlpha = 0.85
      ctx.strokeRect(x1, y1, bw, bh)

      // fill overlay (semi-transparent)
      ctx.fillStyle = color
      ctx.globalAlpha = 0.08
      ctx.fillRect(x1, y1, bw, bh)
      ctx.globalAlpha = 1

      // label background
      const labelShort = player.label === 'player_a' ? 'A' : player.label === 'player_b' ? 'B' : '?'
      const depthLabel = DEPTH_LABELS[player.depth_band] ?? ''
      const sideLabel = player.court_side === 'left' ? '左' : '右'
      const text = `${labelShort} (${depthLabel}/${sideLabel})`

      ctx.font = 'bold 11px system-ui, sans-serif'
      const metrics = ctx.measureText(text)
      const padX = 4
      const padY = 2
      const labelH = 15
      const labelW = metrics.width + padX * 2
      const labelX = x1
      const labelY = y1 > labelH + 2 ? y1 - labelH - 2 : y1 + 2

      ctx.fillStyle = color
      ctx.globalAlpha = 0.9
      ctx.beginPath()
      ctx.roundRect(labelX, labelY, labelW, labelH, 3)
      ctx.fill()
      ctx.globalAlpha = 1

      ctx.fillStyle = '#fff'
      ctx.fillText(text, labelX + padX, labelY + labelH - padY - 1)

      // centroid dot
      const [cx, cy] = player.centroid
      ctx.beginPath()
      ctx.arc(cx * w, cy * h, 3, 0, Math.PI * 2)
      ctx.fillStyle = color
      ctx.globalAlpha = 0.9
      ctx.fill()
      ctx.globalAlpha = 1
    }
  }, [nearestFrame, visible, videoWidth, videoHeight])

  if (!visible) return null

  return (
    <div
      className="absolute inset-0 pointer-events-none"
      style={{ width: videoWidth, height: videoHeight }}
    >
      <canvas
        ref={canvasRef}
        className="absolute inset-0"
        style={{ width: videoWidth, height: videoHeight }}
      />
      {/* research badge */}
      <div className="absolute top-1 right-1 flex items-center gap-1 bg-black/50 rounded px-1.5 py-0.5">
        <span className="text-amber-400 text-[9px] font-bold uppercase tracking-wide">
          assisted
        </span>
      </div>
      {/* no-data hint */}
      {!nearestFrame && frames.length > 0 && (
        <div className="absolute bottom-1 left-1/2 -translate-x-1/2 text-[10px] text-gray-400 bg-black/50 rounded px-2 py-0.5">
          {t('yolo.no_data_at_time', 'この時刻の検出データなし')}
        </div>
      )}
    </div>
  )
}
