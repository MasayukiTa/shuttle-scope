import { useTranslation } from 'react-i18next'
import { clsx } from 'clsx'

interface ConfidenceBadgeProps {
  sampleSize: number
  /** コンパクト表示（モバイル用）: ★マークのみ、タイトルでフル情報 */
  compact?: boolean
  className?: string
}

/**
 * 信頼度バッジ（全解析結果に必ず付与）
 * 500球未満: 警告スタイル（赤枠）
 * 500-2000球: 中程度（黄枠）
 * 2000球以上: 高信頼（緑枠）
 *
 * compact=true: モバイル向けに★のみ表示（タップでツールチップ）
 */
export function ConfidenceBadge({ sampleSize, compact = false, className }: ConfidenceBadgeProps) {
  const { t } = useTranslation()

  // undefined / null / NaN を 0 に正規化（バックエンドが sample_n を省略した場合の保険）
  const size = typeof sampleSize === 'number' && isFinite(sampleSize) ? sampleSize : 0

  let stars: string
  let label: string
  let colorClass: string

  if (size < 500) {
    stars = '★☆☆'
    label = t('confidence.low_label')
    colorClass = 'border-red-400 bg-red-900/30 text-red-300'
  } else if (size < 2000) {
    stars = '★★☆'
    label = t('confidence.medium_label')
    colorClass = 'border-yellow-400 bg-yellow-900/30 text-yellow-300'
  } else {
    stars = '★★★'
    label = t('confidence.high_label')
    colorClass = 'border-green-400 bg-green-900/30 text-green-300'
  }

  if (compact) {
    return (
      <button
        className={clsx('inline-flex items-center px-2 py-0.5 rounded border text-xs font-mono cursor-default', colorClass, className)}
        title={`${label}（${t('confidence.sample_size')}: ${size.toLocaleString()}${t('confidence.strokes')}）`}
        tabIndex={-1}
      >
        {stars}
      </button>
    )
  }

  return (
    <div className={clsx('inline-flex items-center gap-2 px-2 py-1 rounded border text-xs', colorClass, className)}>
      <span className="font-mono">{stars}</span>
      <span>{label}</span>
      <span className="opacity-70">
        ({t('confidence.sample_size')}: {size.toLocaleString()}{t('confidence.strokes')})
      </span>
    </div>
  )
}
