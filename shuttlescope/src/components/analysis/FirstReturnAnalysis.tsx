// ファーストリターン解析コンポーネント（ゾーン別出現率・勝率テーブル）
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { NoDataMessage } from '@/components/common/NoDataMessage'
import { AnalysisFilters, DEFAULT_FILTERS } from '@/types'
import { perfColor, lightSafe, BAR } from '@/styles/colors'
import { useIsLightMode } from '@/hooks/useIsLightMode'

interface FirstReturnAnalysisProps {
  playerId: number
  filters?: AnalysisFilters
}

interface ZoneData {
  zone: string
  count: number
  win_rate: number
  freq_rate: number
}

interface FirstReturnResponse {
  success: boolean
  data: {
    zones: ZoneData[]
    top_zones: string[]
    sample_size: number
  }
  meta: { sample_size: number; confidence: { level: string; stars: string; label: string } }
}

export function FirstReturnAnalysis({ playerId, filters = DEFAULT_FILTERS }: FirstReturnAnalysisProps) {
  const { t } = useTranslation()
  const isLight = useIsLightMode()

  const fp = {
    ...(filters.result !== 'all' ? { result: filters.result } : {}),
    ...(filters.tournamentLevel ? { tournament_level: filters.tournamentLevel } : {}),
    ...(filters.dateFrom ? { date_from: filters.dateFrom } : {}),
    ...(filters.dateTo ? { date_to: filters.dateTo } : {}),
  }
  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-first-return', playerId, filters],
    queryFn: () =>
      apiGet<FirstReturnResponse>('/analysis/first_return_analysis', { player_id: playerId, ...fp }),
    enabled: !!playerId,
  })

  if (isLoading) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.loading')}</div>
  }

  const zones = resp?.data?.zones ?? []
  const topZones = resp?.data?.top_zones ?? []
  const sampleSize = resp?.meta?.sample_size ?? 0

  if (zones.length === 0 || sampleSize === 0) {
    return <NoDataMessage sampleSize={sampleSize} minRequired={5} unit="リターン" />
  }

  return (
    <div className="space-y-3">
      <ConfidenceBadge sampleSize={sampleSize} />

      {topZones.length > 0 && (
        <div className="text-xs text-gray-400">
          {t('analysis.first_return.top_zones')}:
          <span className="ml-2 font-semibold" style={{ color: BAR }}>
            {topZones.map((z) => t(`zones.${z}`, z)).join('・')}
          </span>
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-gray-400 border-b border-gray-700">
              <th className="text-left py-1.5 pr-3">{t('analysis.first_return.zone')}</th>
              <th className="text-center py-1.5 pr-3">{t('auto.FirstReturnAnalysis.k1')}</th>
              <th className="text-center py-1.5 pr-3">{t('analysis.first_return.freq_rate')}</th>
              <th className="text-right py-1.5 pr-2">{t('analysis.first_return.win_rate')}</th>
            </tr>
          </thead>
          <tbody>
            {zones
              .sort((a, b) => b.count - a.count)
              .map((z) => (
                <tr key={z.zone} className="border-b border-gray-700/40 hover:bg-gray-700/20">
                  <td className="py-1.5 pr-3 font-semibold text-white">
                    {t(`zones.${z.zone}`, z.zone)}
                  </td>
                  <td className="py-1.5 pr-3 text-center text-gray-300 num-cell">{z.count}</td>
                  <td className="py-1.5 pr-3 text-center text-gray-300 num-cell">
                    {(z.freq_rate * 100).toFixed(1)}%
                  </td>
                  <td className="py-1.5 pr-2 text-right num-cell">
                    <span
                      className="font-semibold"
                      style={{ color: lightSafe(perfColor(z.win_rate), !isLight) }}
                    >
                      {(z.win_rate * 100).toFixed(1)}%
                    </span>
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
