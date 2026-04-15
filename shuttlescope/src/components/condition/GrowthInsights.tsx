import { useTranslation } from 'react-i18next'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts'
import { useInsights } from '@/hooks/useConditionAnalytics'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { useAuth } from '@/hooks/useAuth'

// 伸びしろインサイト（全ロール表示）
// player: growth_cards のみ、肯定的文言のみ
// coach/analyst: + raw factor trend + validity summary
interface Props {
  playerId: number
  isLight: boolean
}

export function GrowthInsights({ playerId, isLight }: Props) {
  const { t } = useTranslation()
  const { role } = useAuth()
  const { data, isLoading, error } = useInsights(playerId)

  const panelBg = isLight ? 'bg-white' : 'bg-gray-800'
  const borderColor = isLight ? 'border-gray-200' : 'border-gray-700'
  const textMuted = isLight ? 'text-gray-500' : 'text-gray-400'
  const isPlayer = role === 'player'

  const cards = data?.growth_cards ?? []
  const trend = data?.personal_trend

  return (
    <section className={`rounded-lg border ${borderColor} ${panelBg} p-4`}>
      <h2 className="text-sm font-semibold mb-3">
        {isPlayer
          ? t('condition.insights.title_player')
          : t('condition.insights.title_coach')}
      </h2>

      {isLoading ? (
        <div className={`${textMuted} text-xs`}>{t('condition.insights.loading')}</div>
      ) : error ? (
        <div className={`${textMuted} text-xs`}>{t('condition.insights.no_data')}</div>
      ) : (
        <div className="space-y-4">
          {/* growth cards: 横並び */}
          {cards.length > 0 ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {cards.map((c, idx) => (
                <div
                  key={idx}
                  className={`rounded-lg border ${borderColor} p-3 flex flex-col gap-2 ${isLight ? 'bg-gray-50' : 'bg-gray-900'}`}
                >
                  <div className="text-xs font-medium">
                    {t(`condition.insights.growth_card.when.${c.when_key}`, {
                      defaultValue: t('condition.insights.growth_card.when.default', {
                        key: c.when_key,
                      }),
                    })}
                  </div>
                  {c.effect && (
                    <div className="text-sm text-emerald-500 font-semibold">
                      {c.effect}
                    </div>
                  )}
                  <div className="mt-auto">
                    <ConfidenceBadge sampleSize={c.sample_n} compact />
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className={`${textMuted} text-xs`}>
              {t('condition.insights.accumulating')}
            </div>
          )}

          {/* personal trend 表示 */}
          {trend && trend.ccs_28ma != null && (
            <div className={`flex items-center gap-3 text-xs ${textMuted}`}>
              <span>{t('condition.insights.ccs_28ma')}:</span>
              <span className="font-mono">{trend.ccs_28ma.toFixed(1)}</span>
              {trend.direction && (
                <span>
                  {t(`condition.insights.direction.${trend.direction}`)}
                </span>
              )}
            </div>
          )}

          {/* coach/analyst 向け: raw factor trend + validity */}
          {!isPlayer && data?.raw_factor_trends && data.raw_factor_trends.length > 0 && (
            <div className={`pt-3 border-t ${borderColor} space-y-3`}>
              <div className={`text-xs ${textMuted}`}>
                {t('condition.insights.raw_factor_trends')}
              </div>
              {data.raw_factor_trends.map((ft) => (
                <div key={ft.factor}>
                  <div className="text-xs mb-1 font-medium">
                    {t(`condition.factor.${ft.factor}`, { defaultValue: ft.factor })}
                  </div>
                  <div style={{ width: '100%', height: 100 }}>
                    <ResponsiveContainer>
                      <LineChart data={ft.series} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
                        <CartesianGrid
                          strokeDasharray="3 3"
                          stroke={isLight ? '#e5e7eb' : '#374151'}
                        />
                        <XAxis
                          dataKey="date"
                          tick={{ fill: isLight ? '#374151' : '#9ca3af', fontSize: 10 }}
                        />
                        <YAxis tick={{ fill: isLight ? '#374151' : '#9ca3af', fontSize: 10 }} />
                        <Tooltip
                          contentStyle={{
                            backgroundColor: isLight ? '#ffffff' : '#1f2937',
                            border: `1px solid ${isLight ? '#e5e7eb' : '#374151'}`,
                            fontSize: 11,
                          }}
                        />
                        <Line
                          type="monotone"
                          dataKey="value"
                          stroke="#3b82f6"
                          dot={false}
                          strokeWidth={2}
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              ))}
            </div>
          )}

          {!isPlayer && data?.validity_summary && (
            <div className={`pt-3 border-t ${borderColor} text-xs ${textMuted}`}>
              <span className="mr-2">{t('condition.insights.validity_summary')}:</span>
              {data.validity_summary.valid_ratio != null && (
                <span className="font-mono">
                  {(data.validity_summary.valid_ratio * 100).toFixed(0)}%
                </span>
              )}
              {data.validity_summary.flags && data.validity_summary.flags.length > 0 && (
                <span className="ml-2">
                  ({data.validity_summary.flags.join(', ')})
                </span>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  )
}
