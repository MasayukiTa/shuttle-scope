// INFRA Phase B: 重心 (Center of Gravity) 時系列ビュー。
// ConfidenceBadge を必ず付与し、サンプル数が少ない場合は警告を出す。
import { useTranslation } from 'react-i18next'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'

export interface CoGPoint {
  frame_index: number
  side: string
  left_pct: number
  right_pct: number
  forward_lean: number
  stability_score: number
}

interface Props {
  points?: CoGPoint[]
  side?: string
  width?: number
  height?: number
  className?: string
}

export function CoGTimeline({ points, side, width = 360, height = 140, className }: Props) {
  const { t } = useTranslation()

  const filtered = points
    ? side
      ? points.filter((p) => p.side === side)
      : points
    : []

  if (!filtered.length) {
    return (
      <div
        role="status"
        className={`flex items-center justify-center rounded-ss-lg border border-[color:var(--ss-border)] bg-[var(--ss-surface-2)] text-[var(--ss-t2)] text-sm ${className ?? ''}`}
        style={{ width, height }}
      >
        {t('analysis.cog.empty')}
      </div>
    )
  }

  // left_pct (0-1) を y に、frame_index を x に変換
  const n = filtered.length
  const path = filtered
    .map((p, i) => {
      const x = (i / Math.max(n - 1, 1)) * (width - 20) + 10
      const y = (1 - p.left_pct) * (height - 20) + 10
      return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`
    })
    .join(' ')

  return (
    <figure className={className}>
      <div className="mb-1 flex items-center justify-between gap-2">
        <figcaption className="text-sm text-[var(--ss-t1)]">
          {t('analysis.cog.title')}
          {side ? ` (${side})` : null}
        </figcaption>
        {/* サンプル数で信頼度表示（500/2000 球未満で警告）— ConfidenceBadge 自体は不変 */}
        <ConfidenceBadge sampleSize={n} compact />
      </div>
      <svg
        width={width}
        height={height}
        role="img"
        aria-label={t('analysis.cog.title')}
        className="rounded-ss-lg border border-[color:var(--ss-border)] bg-[var(--ss-surface-2)]"
      >
        {/* 50% ライン */}
        <line
          x1={10}
          x2={width - 10}
          y1={height / 2}
          y2={height / 2}
          stroke="var(--ss-border-strong)"
          strokeDasharray="3 3"
        />
        <path d={path} stroke="#f59e0b" strokeWidth={2} fill="none" />
      </svg>
      <p className="ss-num mt-1 text-xs text-[var(--ss-t3)]">
        {t('analysis.cog.axis_hint')}
      </p>
    </figure>
  )
}

export default CoGTimeline
