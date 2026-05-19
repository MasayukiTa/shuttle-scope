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
    colorClass = 'border-red-400 bg-gray-800 text-red-300'
  } else if (size < 2000) {
    stars = '★★☆'
    label = t('confidence.medium_label')
    colorClass = 'border-yellow-400 bg-gray-800 text-amber-400'
  } else {
    stars = '★★★'
    label = t('confidence.high_label')
    colorClass = 'border-green-400 bg-gray-800 text-blue-300'
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

  // 親の幅に対して縮みやすく / はみ出さないように max-w-full + whitespace-nowrap
  // + overflow-hidden を入れる。狭い親では label / sample-size 部分を CSS で
  // 非表示にして ★ だけ残す (= 自動コンパクト)。
  // user 報告 (mobile): 高信頼バッジが枠を突き破る / タイトル側が縦書きになる。
  return (
    <div
      className={clsx(
        'inline-flex items-center gap-2 px-2 py-1 rounded border text-xs',
        'max-w-full overflow-hidden whitespace-nowrap shrink',
        colorClass,
        className,
      )}
      title={`${label}（${t('confidence.sample_size')}: ${size.toLocaleString()}${t('confidence.strokes')})`}
    >
      <span className="font-mono shrink-0">{stars}</span>
      <span className="hidden sm:inline truncate">{label}</span>
      <span className="hidden md:inline opacity-70 truncate">
        ({t('confidence.sample_size')}: {size.toLocaleString()}{t('confidence.strokes')})
      </span>
    </div>
  )
}
