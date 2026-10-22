/**
 * DateRangeFilter — 期間フィルター
 *
 * 試合一覧等で日付範囲による絞り込みに使用。
 * プリセット（直近1ヶ月、3ヶ月、半年、1年、全期間）+ カスタム日付入力。
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { clsx } from 'clsx'
import { MIcon } from '@/components/common/MIcon'
import { isReversedRange, presetFromDate, type RangePreset } from '@/utils/localDate'

interface DateRangeFilterProps {
  from: string
  to: string
  onChange: (from: string, to: string) => void
  className?: string
}

type Preset = RangePreset

/** プリセットの開始日 (ローカル暦の YYYY-MM-DD)。UTC 日付に変換しない (監査 #796)。 */
function computePresetFrom(preset: Preset): string {
  return presetFromDate(preset)
}

function detectPreset(from: string): Preset | null {
  if (!from) return 'all'
  const presets: Preset[] = ['1m', '3m', '6m', '1y']
  for (const p of presets) {
    if (computePresetFrom(p) === from) return p
  }
  return null
}

const PRESET_LABELS: Record<Preset, string> = {
  '1m': '1ヶ月',
  '3m': '3ヶ月',
  '6m': '半年',
  '1y': '1年',
  'all': '全期間',
}

export function DateRangeFilter({ from, to, onChange, className }: DateRangeFilterProps) {
  const { t } = useTranslation()
  const [showCustom, setShowCustom] = useState(false)
  const [rangeError, setRangeError] = useState(false)
  const activePreset = detectPreset(from)

  // 開始日 > 終了日は受け付けず、その場で理由を示す (監査 #797)
  const handleCustom = (nextFrom: string, nextTo: string) => {
    if (isReversedRange(nextFrom, nextTo)) {
      setRangeError(true)
      return
    }
    setRangeError(false)
    onChange(nextFrom, nextTo)
  }

  const handlePreset = (p: Preset) => {
    setShowCustom(false)
    setRangeError(false)
    onChange(computePresetFrom(p), '')
  }

  return (
    <div className={clsx('flex items-center gap-1.5 flex-wrap', className)}>
      <MIcon name="calendar_month" size={13} className="text-[var(--ss-t3)] shrink-0" />
      {(Object.entries(PRESET_LABELS) as [Preset, string][]).map(([key, label]) => (
        <button
          key={key}
          onClick={() => handlePreset(key)}
          className={clsx(
            'px-2 py-0.5 rounded-ss-pill text-xs transition-colors duration-fast ease-out',
            activePreset === key && !showCustom
              ? 'bg-[var(--ss-brand)] text-white'
              : 'bg-[var(--ss-surface-2)] text-[var(--ss-t2)] hover:text-[var(--ss-t1)] hover:bg-[var(--ss-surface-3)]',
          )}
        >
          {label}
        </button>
      ))}
      <button
        onClick={() => setShowCustom((v) => !v)}
        className={clsx(
          'px-2 py-0.5 rounded-ss-pill text-xs transition-colors duration-fast ease-out',
          showCustom
            ? 'bg-[var(--ss-brand)] text-white'
            : 'bg-[var(--ss-surface-2)] text-[var(--ss-t2)] hover:text-[var(--ss-t1)] hover:bg-[var(--ss-surface-3)]',
        )}
      >
        {t('auto.DateRangeFilter.custom_range')}
      </button>
      {showCustom && (
        <div className="flex items-center gap-1 text-xs">
          <input
            type="date"
            value={from}
            max={to || undefined}
            aria-invalid={rangeError}
            onChange={(e) => handleCustom(e.target.value, to)}
            className="ss-num bg-[var(--ss-ctrl-bg)] border border-[var(--ss-ctrl-border)] rounded-ss-md px-1.5 py-0.5 text-xs text-[var(--ss-ctrl-text)]"
          />
          <span className="text-[var(--ss-t3)]">{t('auto.DateRangeFilter.range_sep')}</span>
          <input
            type="date"
            value={to}
            min={from || undefined}
            aria-invalid={rangeError}
            onChange={(e) => handleCustom(from, e.target.value)}
            className="ss-num bg-[var(--ss-ctrl-bg)] border border-[var(--ss-ctrl-border)] rounded-ss-md px-1.5 py-0.5 text-xs text-[var(--ss-ctrl-text)]"
          />
          {rangeError && (
            <span role="alert" className="text-red-400">
              {t('auto.DateRangeFilter.range_reversed')}
            </span>
          )}
        </div>
      )}
    </div>
  )
}
