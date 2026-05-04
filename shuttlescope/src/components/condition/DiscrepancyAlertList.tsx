import { useTranslation } from 'react-i18next'
import { useDiscrepancy, DiscrepancyItem } from '@/hooks/useConditionAnalytics'
import { useAuth } from '@/hooks/useAuth'

// 乖離アラートリスト（coach/analyst only）
// player にはこのコンポーネント自体をマウントしない呼び出し側で制御
interface Props {
  playerId: number
  isLight: boolean
}

function severityClass(sev: DiscrepancyItem['severity']): string {
  switch (sev) {
    case 'high':
      return 'bg-red-500/20 text-red-400 border-red-500/40'
    case 'medium':
      return 'bg-amber-500/20 text-amber-400 border-amber-500/40'
    default:
      return 'bg-gray-500/20 text-gray-400 border-gray-500/40'
  }
}

export function DiscrepancyAlertList({ playerId, isLight }: Props) {
  const { t } = useTranslation()
  const { data, isLoading, error } = useDiscrepancy(playerId)

  const panelBg = isLight ? 'bg-white' : 'bg-gray-800'
  const borderColor = isLight ? 'border-gray-200' : 'border-gray-700'
  const textMuted = isLight ? 'text-gray-500' : 'text-gray-400'
  const items = data ?? []

  return (
    <section className={`rounded-lg border ${borderColor} ${panelBg} p-4`}>
      <h2 className="text-sm font-semibold mb-3">{t('condition.discrepancy.title')}</h2>

      {isLoading ? (
        <div className={`${textMuted} text-xs`}>{t('condition.discrepancy.loading')}</div>
      ) : error ? (
        <div className={`${textMuted} text-xs`}>{t('condition.discrepancy.no_data')}</div>
      ) : items.length === 0 ? (
        <div className={`${textMuted} text-xs`}>{t('condition.discrepancy.no_data')}</div>
      ) : (
        <ul className="space-y-2">
          {items.map((it) => (
            <li
              key={it.condition_id + '-' + it.date}
              className={`flex items-start gap-3 px-3 py-2 rounded border ${borderColor}`}
            >
              <span
                className={`shrink-0 px-2 py-0.5 rounded border text-[10px] font-mono uppercase ${severityClass(it.severity)}`}
              >
                {t(`condition.discrepancy.severity.${it.severity}`)}
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-xs flex items-center gap-2">
                  <span className={textMuted}>{it.date}</span>
                  <span className="font-medium">
                    {t(`condition.discrepancy.type.${it.type}`, { defaultValue: it.type })}
                  </span>
                </div>
                {it.detail && <div className={`text-xs ${textMuted} mt-1`}>{it.detail}</div>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
