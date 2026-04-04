import { useTranslation } from 'react-i18next'
import { clsx } from 'clsx'

interface ConfidenceBadgeProps {
  sampleSize: number
  className?: string
}

/**
 * 信頼度バッジ（全解析結果に必ず付与）
 * 500球未満: 警告スタイル（赤枠）
 * 500-2000球: 中程度（黄枠）
 * 2000球以上: 高信頼（緑枠）
 */
export function ConfidenceBadge({ sampleSize, className }: ConfidenceBadgeProps) {
  const { t } = useTranslation()

  let stars: string
  let label: string
  let colorClass: string

  if (sampleSize < 500) {
    stars = '★☆☆'
    label = t('confidence.low_label')
    colorClass = 'border-red-400 bg-red-900/30 text-red-300'
  } else if (sampleSize < 2000) {
    stars = '★★☆'
    label = t('confidence.medium_label')
    colorClass = 'border-yellow-400 bg-yellow-900/30 text-yellow-300'
  } else {
    stars = '★★★'
    label = t('confidence.high_label')
    colorClass = 'border-green-400 bg-green-900/30 text-green-300'
  }

  return (
    <div className={clsx('inline-flex items-center gap-2 px-2 py-1 rounded border text-xs', colorClass, className)}>
      <span className="font-mono">{stars}</span>
      <span>{label}</span>
      <span className="opacity-70">
        ({t('confidence.sample_size')}: {sampleSize.toLocaleString()}{t('confidence.strokes')})
      </span>
    </div>
  )
}
