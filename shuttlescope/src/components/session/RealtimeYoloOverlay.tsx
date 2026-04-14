/**
 * ブラウザ中継受信映像の上に person bbox を重ねる overlay canvas。
 *
 * video 要素に親要素を共有する absolute 配置。videoRef の表示サイズを ResizeObserver で
 * 追跡し、正規化座標の bbox を実寸にスケールして描画する。
 */
import { useEffect, useRef } from 'react'
import type { RealtimeBox } from '@/hooks/useRealtimeYolo'

export function RealtimeYoloOverlay({
  videoRef,
  boxes,
  color = '#22c55e',
}: {
  videoRef: React.RefObject<HTMLVideoElement>
  boxes: RealtimeBox[]
  color?: string
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    const video = videoRef.current
    if (!canvas || !video) return

    const render = () => {
      const rect = video.getBoundingClientRect()
      const dpr = window.devicePixelRatio || 1
      const w = Math.max(1, Math.round(rect.width * dpr))
      const h = Math.max(1, Math.round(rect.height * dpr))
      if (canvas.width !== w) canvas.width = w
      if (canvas.height !== h) canvas.height = h
      canvas.style.width = `${rect.width}px`
      canvas.style.height = `${rect.height}px`
      const ctx = canvas.getContext('2d')
      if (!ctx) return
      ctx.clearRect(0, 0, w, h)
      if (!boxes.length) return
      ctx.lineWidth = Math.max(2, Math.round(2 * dpr))
      ctx.strokeStyle = color
      ctx.fillStyle = color
      ctx.font = `${Math.round(12 * dpr)}px system-ui, sans-serif`
      for (const b of boxes) {
        const x = b.x1 * w
        const y = b.y1 * h
        const bw = (b.x2 - b.x1) * w
        const bh = (b.y2 - b.y1) * h
        ctx.strokeRect(x, y, bw, bh)
        const label = `person ${Math.round(b.conf * 100)}%`
        const tw = ctx.measureText(label).width + 6 * dpr
        const th = 16 * dpr
        ctx.fillRect(x, Math.max(0, y - th), tw, th)
        ctx.save()
        ctx.fillStyle = '#000'
        ctx.fillText(label, x + 3 * dpr, Math.max(th - 4 * dpr, y - 4 * dpr))
        ctx.restore()
      }
    }

    render()
    const ro = new ResizeObserver(render)
    ro.observe(video)
    return () => ro.disconnect()
  }, [boxes, color, videoRef])

  return (
    <canvas
      ref={canvasRef}
      className="pointer-events-none absolute inset-0"
      style={{ mixBlendMode: 'normal' }}
    />
  )
}
