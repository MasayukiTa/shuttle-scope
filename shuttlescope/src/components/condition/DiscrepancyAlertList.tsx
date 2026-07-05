import { useTranslation } from 'react-i18next'
import { useDiscrepancy, DiscrepancyItem } from '@/hooks/useConditionAnalytics'
import { _useAuth } from '@/hooks/useAuth'

// 乖離アラートリスト（coach/analyst only）
// player にはこのコンポーネント自体をマウントしない呼び出し側で制御
interface Props {
  playerId: number
  isLight: boolean
}

function severityClass(sev: DiscrepancyItem['severity']): string {
  switch (sev) {
    case 'high':
      return 'bg-[var(--ss-danger-tint)] text-[var(--ss-bad)] border-[var(--ss-danger-border)]'
    case 'medium':
      return 'bg-[var(--ss-warn-tint)] text-[var(--ss-warn)] border-[var(--ss-warning-border)]'
    default:
      return 'bg-[var(--ss-surface-2)] text-[var(--ss-t2)] border-[var(--ss-border)]'
  }
}

export function DiscrepancyAlertList({ playerId, isLight }: Props) {
  const { t } = useTranslation()
  const { data, isLoading, error } = useDiscrepancy(playerId)

  const panelBg = 'bg-[var(--ss-surface-1)]'
  const borderColor = 'border-[var(--ss-border)]'
  const textMuted = 'text-[var(--ss-t2)]'
  const items = data ?? []

  return (
    <section className={`rounded-ss-lg border shadow-card ${borderColor} ${panelBg} p-4`}>
      <h2 className="text-sm font-semibold text-[var(--ss-t1)] mb-3">{t('condition.discrepancy.title')}</h2>

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
              className={`flex items-start gap-3 px-3 py-2 rounded-ss-sm border ${borderColor}`}
            >
              <span
                className={`shrink-0 px-2 py-0.5 rounded-ss-sm border text-[10px] font-mono uppercase ${severityClass(it.severity)}`}
              >
                {t(`condition.discrepancy.severity.${it.severity}`)}
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-xs flex items-center gap-2">
                  <span className={`ss-num ${textMuted}`}>{it.date}</span>
                  <span className="font-medium text-[var(--ss-t1)]">
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
