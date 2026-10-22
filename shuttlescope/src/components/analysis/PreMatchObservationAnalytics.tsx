// 補助観察インサイト：試合前観察条件別の勝率傾向（PREMATCH_OBSERVATION_ANALYTICS_v1）
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiGet } from '@/api/client'
import { WIN, LOSS } from '@/styles/colors'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { QueryErrorNotice } from '@/components/common/QueryErrorNotice'

interface PreMatchObservationAnalyticsProps {
  playerId: number
}

interface SplitEntry {
  observation_type: string
  observation_value: string
  win_rate: number
  wins: number
  match_count: number
  confidence: 'unknown' | 'tentative' | 'likely' | 'confirmed'
}

interface ObsAnalyticsResponse {
  success: boolean
  data: {
    splits: SplitEntry[]
    observation_count: number
    self_observations: SplitEntry[]
  }
  meta: { sample_size: number }
}

const CONF_COLOR: Record<string, string> = {
  confirmed: '#22c55e',
  likely:    '#3b82f6',
  tentative: '#eab308',
  unknown:   '#6b7280',
}

const KNOWN_CONFIDENCE = ['confirmed', 'likely', 'tentative', 'unknown']
const KNOWN_TYPES = [
  'handedness',
  'physical_caution',
  'tactical_style',
  'court_preference',
  'self_condition',
  'self_timing',
]

export function PreMatchObservationAnalytics({ playerId }: PreMatchObservationAnalyticsProps) {
  const { t } = useTranslation()
  const isLight = useIsLightMode()

  const { data: resp, isLoading, isError, refetch } = useQuery({
    queryKey: ['analysis-observation-analytics', playerId],
    queryFn: () => apiGet<ObsAnalyticsResponse>('/analysis/observation_analytics', { player_id: playerId }),
    enabled: !!playerId,
  })

  // 観察種別・観察入力者の確信度ラベル。未知の値は内部コードを出さず共通表示にする
  const typeLabel = (obsType: string): string =>
    KNOWN_TYPES.includes(obsType)
      ? t(`warmup.observation_${obsType}`)
      : t('observation_analytics.unknown_value')
  // 観察入力者が付けた確信度であり、勝率の統計的な確からしさではない
  const confidenceBadge = (conf: string): string =>
    t('observation_analytics.confidence_badge', {
      label: KNOWN_CONFIDENCE.includes(conf)
        ? t(`warmup.confidence_${conf}`)
        : t('observation_analytics.unknown_value'),
    })

  const labelColor = isLight ? '#475569' : '#9ca3af'
  const rowBg      = isLight ? '#f8fafc' : '#1f2937'
  const rowBorder  = isLight ? '#e2e8f0' : '#374151'
  const textMain   = isLight ? '#1e293b' : '#e2e8f0'

  if (isLoading) {
    return <div className="text-[var(--ss-t3)] text-sm py-3 text-center">{t('analysis.loading')}</div>
  }

  if (isError) {
    return <QueryErrorNotice onRetry={() => { void refetch() }} />
  }

  const splits = resp?.data?.splits ?? []
  const selfObs = resp?.data?.self_observations ?? []
  const sampleSize = resp?.meta?.sample_size ?? 0

  if (splits.length === 0 && selfObs.length === 0) {
    return (
      <p className="text-xs py-3 text-center" style={{ color: labelColor }}>
        {t('observation_analytics.no_data', '観察記録が蓄積されると表示されます')}
      </p>
    )
  }

  // observation_type 単位でグループ化
  const grouped: Record<string, SplitEntry[]> = {}
  for (const entry of splits) {
    if (!grouped[entry.observation_type]) grouped[entry.observation_type] = []
    grouped[entry.observation_type].push(entry)
  }

  return (
    <div className="space-y-4">
      <p className="text-[10px]" style={{ color: labelColor }}>
        {t('observation_analytics.subtitle')}
        {t('auto.PreMatchObservationAnalytics.n_matches', { n: sampleSize })}
      </p>

      {Object.entries(grouped).map(([obsType, entries]) => (
        <div key={obsType}>
          <p className="text-xs font-semibold mb-1.5" style={{ color: textMain }}>
            {typeLabel(obsType)}
          </p>
          <div className="space-y-1.5">
            {entries.map((entry) => {
              const wr = entry.win_rate
              const barColor = wr >= 0.5 ? WIN : LOSS
              const confColor = CONF_COLOR[entry.confidence] ?? CONF_COLOR.unknown

              // 観察値の日本語ラベル（warmup i18n キーにフォールバック）
              const valTypePrefix = obsType === 'handedness' ? 'handedness_'
                : obsType === 'physical_caution' ? 'physical_'
                : obsType === 'tactical_style' ? 'tactical_'
                : obsType === 'court_preference' ? 'court_'
                : obsType === 'self_condition' ? 'self_condition_'
                : obsType === 'self_timing' ? 'self_timing_'
                : ''
              const valueLabel = t(
                `warmup.value_${valTypePrefix}${entry.observation_value}`,
                entry.observation_value,
              )

              return (
                <div
                  key={entry.observation_value}
                  className="rounded-ss-md p-2 bg-[var(--ss-surface-2)] border border-[var(--ss-border)]"
                >
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-1.5">
                      <span className="text-xs" style={{ color: textMain }}>{valueLabel}</span>
                      <span
                        className="text-[9px] px-1 rounded-ss-sm"
                        style={{ color: confColor, border: `1px solid ${confColor}`, opacity: 0.85 }}
                      >
                        {confidenceBadge(entry.confidence)}
                      </span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <span className="text-xs font-semibold ss-num" style={{ color: barColor }}>
                        {(wr * 100).toFixed(0)}%
                      </span>
                      <span className="text-[10px] ss-num" style={{ color: labelColor }}>
                        {t('auto.PreMatchObservationAnalytics.win_loss', { w: entry.wins, l: entry.match_count - entry.wins })}
                      </span>
                    </div>
                  </div>
                  {/* 勝率バー */}
                  <div
                    className="w-full rounded-ss-md h-1 overflow-hidden bg-[var(--ss-surface-3)]"
                  >
                    <div
                      className="h-1 rounded-ss-md duration-base ease-out"
                      style={{ width: `${(wr * 100).toFixed(0)}%`, backgroundColor: barColor }}
                    />
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      ))}

      {/* 自コンディション分析 */}
      {selfObs.length > 0 && (
        <div className="border-t border-[var(--ss-border)] pt-3">
          <p className="text-xs font-semibold mb-2" style={{ color: textMain }}>
            {t('observation_analytics.self_section', '自コンディション条件別傾向')}
          </p>
          {(() => {
            const selfGrouped: Record<string, SplitEntry[]> = {}
            for (const entry of selfObs) {
              if (!selfGrouped[entry.observation_type]) selfGrouped[entry.observation_type] = []
              selfGrouped[entry.observation_type].push(entry)
            }
            return Object.entries(selfGrouped).map(([obsType, entries]) => (
              <div key={obsType} className="mb-2">
                <p className="text-[11px] mb-1" style={{ color: labelColor }}>
                  {typeLabel(obsType)}
                </p>
                <div className="space-y-1">
                  {entries.map((entry) => {
                    const wr = entry.win_rate
                    const barColor = wr >= 0.5 ? WIN : LOSS
                    const labelKey = obsType === 'self_condition' ? `warmup.value_self_condition_${entry.observation_value}`
                      : `warmup.value_self_timing_${entry.observation_value}`
                    return (
                      <div key={entry.observation_value}
                        className="flex items-center gap-2 rounded-ss-md p-1.5 bg-[var(--ss-surface-2)] border border-[var(--ss-border)]"
                      >
                        <span className="text-[11px] flex-1" style={{ color: textMain }}>
                          {t(labelKey, entry.observation_value)}
                        </span>
                        <span className="text-[11px] font-semibold ss-num" style={{ color: barColor }}>
                          {(wr * 100).toFixed(0)}%
                        </span>
                        <span className="text-[10px] ss-num" style={{ color: labelColor }}>
                          {t('auto.PreMatchObservationAnalytics.win_loss', { w: entry.wins, l: entry.match_count - entry.wins })}
                        </span>
                      </div>
                    )
                  })}
                </div>
              </div>
            ))
          })()}
        </div>
      )}

      <p className="text-[9px]" style={{ color: labelColor }}>
        {t('auto.PreMatchObservationAnalytics.footer_note')}
      </p>
    </div>
  )
}
