// INFRA Phase B: シャトル軌跡 2D プロット。
// データが無い場合は「未解析」バッジを表示し、既存画面を壊さない。
import { useTranslation } from 'react-i18next'

export interface ShuttleTrackPoint {
  frame_index: number
  ts_sec: number
  x: number | null
  y: number | null
  confidence: number
}

interface Props {
  points?: ShuttleTrackPoint[]
  width?: number
  height?: number
  className?: string
}

export function ShuttleTrackView({ points, width = 320, height = 240, className }: Props) {
  const { t } = useTranslation()

  // 未解析ガード: null / 空配列は未解析として扱う
  if (!points || points.length === 0) {
    return (
      <div
        role="status"
        className={`flex items-center justify-center rounded-ss-lg border border-[color:var(--ss-border)] bg-[var(--ss-surface-2)] text-[var(--ss-t2)] text-sm ${className ?? ''}`}
        style={{ width, height }}
      >
        {t('analysis.shuttle_track.empty')}
      </div>
    )
  }

  // 正規化座標 (0-1) を SVG 座標へ変換
  const valid = points.filter((p) => p.x != null && p.y != null)
  const path = valid
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${(p.x! * width).toFixed(1)} ${(p.y! * height).toFixed(1)}`)
    .join(' ')

  return (
    <figure className={className}>
      <figcaption className="mb-1 text-sm text-[var(--ss-t1)]">
        {t('analysis.shuttle_track.title')}
      </figcaption>
      <svg
        width={width}
        height={height}
        role="img"
        aria-label={t('analysis.shuttle_track.title')}
        className="rounded-ss-lg border border-[color:var(--ss-border)] bg-[var(--ss-surface-2)]"
      >
        <rect x={0} y={0} width={width} height={height} fill="transparent" />
        {/* コート外枠（ヒント） */}
        <rect x={10} y={10} width={width - 20} height={height - 20} stroke="var(--ss-border-strong)" fill="none" strokeDasharray="4 3" />
        <path d={path} stroke="#38bdf8" strokeWidth={2} fill="none" />
        {valid.map((p) => (
          <circle
            key={p.frame_index}
            cx={p.x! * width}
            cy={p.y! * height}
            r={2}
            fill="#38bdf8"
            opacity={Math.max(0.2, p.confidence)}
          />
        ))}
      </svg>
      <p className="ss-num mt-1 text-xs text-[var(--ss-t3)]">
        {t('analysis.shuttle_track.sample_size', { count: valid.length })}
      </p>
    </figure>
  )
}

export default ShuttleTrackView
