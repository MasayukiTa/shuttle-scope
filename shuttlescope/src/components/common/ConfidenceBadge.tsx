import { useTranslation } from 'react-i18next'
import { clsx } from 'clsx'
import { MIcon } from '@/components/common/MIcon'

/** N 個 filled star + (max-N) 個 outline star を MIcon で描画 */
function StarLevel({ filled, max = 3, size = 12 }: { filled: number; max?: number; size?: number }) {
  return (
    <span className="inline-flex items-center shrink-0" aria-hidden="true">
      {Array.from({ length: max }, (_, i) => (
        <MIcon key={i} name={i < filled ? 'star' : 'star_border'} size={size} />
      ))}
    </span>
  )
}

/**
 * 標本の単位。**閾値も表示も単位で変わるので、必ず実際の単位を渡すこと。**
 *
 * D-5: 既定の閾値 (500 / 2000) は打球数のものだが、呼び出し側は
 * 試合数・ラリー数・打球数のどれも渡していた。試合数が 500 を超えることは
 * 無いので、試合数を渡していた画面は**永久に★1つ・赤の「参考値」**に固定され、
 * しかもツールチップは「球」と表示していた。値も単位も誤りだった。
 */
export type SampleUnit = 'strokes' | 'rallies' | 'matches'

/** 単位ごとの [中程度, 高信頼] 閾値。 */
const THRESHOLDS: Record<SampleUnit, [number, number]> = {
  // 既存の打球数基準を踏襲
  strokes: [500, 2000],
  // 1 ラリー平均 8 打前後なので、打球数基準を概ね対応させた値
  rallies: [60, 250],
  // backend/utils/confidence.py の opponent_analysis (30 試合) に合わせる
  matches: [10, 30],
}

interface ConfidenceBadgeProps {
  sampleSize: number
  /** 標本の単位。既定は従来どおり打球数。 */
  unit?: SampleUnit
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
export function ConfidenceBadge({ sampleSize, unit = 'strokes', compact = false, className }: ConfidenceBadgeProps) {
  const { t } = useTranslation()

  // undefined / null / NaN を 0 に正規化（バックエンドが sample_n を省略した場合の保険）
  const size = typeof sampleSize === 'number' && isFinite(sampleSize) ? sampleSize : 0

  let filled: number
  let label: string
  let colorClass: string

  // tier の色分け（赤=低 / 黄=中 / 緑=高）は情報量なので維持。
  // v2: token 化した status カラー (tint bg + colored text + hairline border) を
  // 両テーマで共有し、テーマ分岐の手書き if を廃止。
  const [midThreshold, highThreshold] = THRESHOLDS[unit]
  if (size < midThreshold) {
    filled = 1
    label = t('confidence.low_label')
    colorClass = 'border-[var(--ss-danger-border)] bg-[var(--ss-danger-bg)] text-[var(--ss-danger-text)]'
  } else if (size < highThreshold) {
    filled = 2
    label = t('confidence.medium_label')
    colorClass = 'border-[var(--ss-warning-border)] bg-[var(--ss-warning-bg)] text-[var(--ss-warning-text)]'
  } else {
    filled = 3
    label = t('confidence.high_label')
    colorClass = 'border-[var(--ss-info-border)] bg-[var(--ss-info-bg)] text-[var(--ss-info-text)]'
  }

  if (compact) {
    return (
      <button
        className={clsx('inline-flex items-center px-2 py-0.5 rounded-ss-pill border text-xs font-mono cursor-default', colorClass, className)}
        title={`${label}（${t('confidence.sample_size')}: ${size.toLocaleString()}${t(`confidence.unit_${unit}`)}）`}
        tabIndex={-1}
      >
        <StarLevel filled={filled} />
      </button>
    )
  }

  // 親の幅に対して縮みやすく / はみ出さないように max-w-full + whitespace-nowrap
  // + overflow-hidden を入れる。狭い親では label / sample-size 部分を CSS で
  // 非表示にして ★ だけ残す (= 自動コンパクト)。
  // user 報告 (mobile): 高信頼バッジが枠を突き破る / タイトル側が縦書きになる。
  // v2: 真の status chip なので rounded-ss-pill (restrained pill) を使う。
  return (
    <div
      className={clsx(
        'inline-flex items-center gap-2 px-2.5 py-1 rounded-ss-pill border text-xs',
        'max-w-full overflow-hidden whitespace-nowrap shrink',
        colorClass,
        className,
      )}
      title={`${label}（${t('confidence.sample_size')}: ${size.toLocaleString()}${t(`confidence.unit_${unit}`)})`}
    >
      <StarLevel filled={filled} />
      <span className="hidden sm:inline truncate">{label}</span>
      <span className="hidden md:inline opacity-70 truncate ss-num">
        ({t('confidence.sample_size')}: {size.toLocaleString()}{t(`confidence.unit_${unit}`)})
      </span>
    </div>
  )
}
