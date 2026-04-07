// セット分布（2-0/2-1/1-2/0-2）の確率横棒グラフ
import { useTranslation } from 'react-i18next'
import { WIN, LOSS } from '@/styles/colors'
import { useIsLightMode } from '@/hooks/useIsLightMode'

interface SetDistributionBarProps {
  distribution: {
    '2-0': number
    '2-1': number
    '1-2': number
    '0-2': number
  }
}

const OUTCOMES = [
  { key: '2-0' as const, labelKey: 'prediction.set_outcome_20', win: true },
  { key: '2-1' as const, labelKey: 'prediction.set_outcome_21', win: true },
  { key: '1-2' as const, labelKey: 'prediction.set_outcome_12', win: false },
  { key: '0-2' as const, labelKey: 'prediction.set_outcome_02', win: false },
]

export function SetDistributionBar({ distribution }: SetDistributionBarProps) {
  const { t } = useTranslation()
  const isLight = useIsLightMode()
  const labelColor = isLight ? '#334155' : '#d1d5db'

  return (
    <div className="space-y-2">
      {OUTCOMES.map(({ key, labelKey, win }) => {
        const pct = Math.round((distribution[key] ?? 0) * 100)
        const color = win ? WIN : LOSS
        return (
          <div key={key} className="flex items-center gap-3">
            <span className="text-xs w-16 shrink-0" style={{ color: labelColor }}>
              {t(labelKey)}
            </span>
            <div className="flex-1 bg-gray-700 rounded-full h-4 overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{ width: `${pct}%`, backgroundColor: color }}
              />
            </div>
            <span
              className="text-xs w-10 text-right font-mono font-semibold shrink-0"
              style={{ color }}
            >
              {pct}%
            </span>
          </div>
        )
      })}
    </div>
  )
}
