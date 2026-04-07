// 補助観察インサイト：試合前観察条件別の勝率傾向（PREMATCH_OBSERVATION_ANALYTICS_v1）
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiGet } from '@/api/client'
import { WIN, LOSS } from '@/styles/colors'
import { useIsLightMode } from '@/hooks/useIsLightMode'

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
  }
  meta: { sample_size: number }
}

const CONF_COLOR: Record<string, string> = {
  confirmed: '#22c55e',
  likely:    '#3b82f6',
  tentative: '#eab308',
  unknown:   '#6b7280',
}

const CONF_LABEL: Record<string, string> = {
  confirmed: '確認済',
  likely:    'ほぼ確か',
  tentative: '仮説',
  unknown:   '不明',
}

// observation_type → 日本語ラベルマップ（ja.json の warmup キーに対応）
const TYPE_LABEL: Record<string, string> = {
  handedness:       '利き手',
  physical_caution: '身体的注意',
  tactical_style:   '戦術スタイル',
  court_preference: 'コート位置',
}

export function PreMatchObservationAnalytics({ playerId }: PreMatchObservationAnalyticsProps) {
  const { t } = useTranslation()
  const isLight = useIsLightMode()

  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-observation-analytics', playerId],
    queryFn: () => apiGet<ObsAnalyticsResponse>('/analysis/observation_analytics', { player_id: playerId }),
    enabled: !!playerId,
  })

  const labelColor = isLight ? '#475569' : '#9ca3af'
  const rowBg      = isLight ? '#f8fafc' : '#1f2937'
  const rowBorder  = isLight ? '#e2e8f0' : '#374151'
  const textMain   = isLight ? '#1e293b' : '#e2e8f0'

  if (isLoading) {
    return <div className="text-gray-500 text-sm py-3 text-center">{t('analysis.loading')}</div>
  }

  const splits = resp?.data?.splits ?? []
  const sampleSize = resp?.meta?.sample_size ?? 0

  if (splits.length === 0) {
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
        {t('observation_analytics.subtitle', '試合前観察記録に基づく参考傾向（少数サンプル・主観的データを含む）')}
        　N={sampleSize}試合
      </p>

      {Object.entries(grouped).map(([obsType, entries]) => (
        <div key={obsType}>
          <p className="text-xs font-semibold mb-1.5" style={{ color: textMain }}>
            {TYPE_LABEL[obsType] ?? obsType}
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
                : ''
              const valueLabel = t(
                `warmup.value_${valTypePrefix}${entry.observation_value}`,
                entry.observation_value,
              )

              return (
                <div
                  key={entry.observation_value}
                  className="rounded p-2"
                  style={{ backgroundColor: rowBg, border: `1px solid ${rowBorder}` }}
                >
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-1.5">
                      <span className="text-xs" style={{ color: textMain }}>{valueLabel}</span>
                      <span
                        className="text-[9px] px-1 rounded"
                        style={{ color: confColor, border: `1px solid ${confColor}`, opacity: 0.85 }}
                      >
                        {CONF_LABEL[entry.confidence] ?? entry.confidence}
                      </span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <span className="text-xs font-semibold" style={{ color: barColor }}>
                        {(wr * 100).toFixed(0)}%
                      </span>
                      <span className="text-[10px]" style={{ color: labelColor }}>
                        {entry.wins}勝{entry.match_count - entry.wins}敗
                      </span>
                    </div>
                  </div>
                  {/* 勝率バー */}
                  <div
                    className="w-full rounded-full h-1 overflow-hidden"
                    style={{ backgroundColor: isLight ? '#e2e8f0' : '#374151' }}
                  >
                    <div
                      className="h-1 rounded-full"
                      style={{ width: `${(wr * 100).toFixed(0)}%`, backgroundColor: barColor }}
                    />
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      ))}

      <p className="text-[9px]" style={{ color: labelColor }}>
        ※ 参考傾向（観察ベースの補助分析）。主要分析の補足として参照してください。
      </p>
    </div>
  )
}
