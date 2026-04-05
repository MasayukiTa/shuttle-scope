// 対戦相手別統計テーブルコンポーネント（アナリスト・コーチ向け）
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { RoleGuard } from '@/components/common/RoleGuard'

interface OpponentStatsProps {
  playerId: number
}

interface OpponentData {
  opponent_id: number
  opponent_name: string
  match_count: number
  win_rate: number
  avg_rally_length: number
  sample_size: number
}

interface OpponentStatsResponse {
  success: boolean
  data: { opponents: OpponentData[] }
  meta: { sample_size: number; confidence: { level: string; stars: string; label: string } }
}

function OpponentTable({ playerId }: { playerId: number }) {
  const { t } = useTranslation()

  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-opponent-stats', playerId],
    queryFn: () =>
      apiGet<OpponentStatsResponse>('/analysis/opponent_stats', { player_id: playerId }),
    enabled: !!playerId,
  })

  if (isLoading) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.loading')}</div>
  }

  const opponents = resp?.data?.opponents ?? []
  const sampleSize = resp?.meta?.sample_size ?? 0

  if (opponents.length === 0) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.no_data')}</div>
  }

  return (
    <div className="space-y-3">
      <ConfidenceBadge sampleSize={sampleSize} />

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-gray-400 border-b border-gray-700">
              <th className="text-left py-1.5 pr-3">{t('analysis.opponent_stats.opponent')}</th>
              <th className="text-center py-1.5 pr-3">{t('analysis.opponent_stats.match_count')}</th>
              <th className="text-center py-1.5 pr-3">{t('analysis.opponent_stats.win_rate')}</th>
              <th className="text-right py-1.5">{t('analysis.opponent_stats.avg_rally')}</th>
            </tr>
          </thead>
          <tbody>
            {opponents
              .sort((a, b) => b.match_count - a.match_count)
              .map((opp) => (
                <tr
                  key={opp.opponent_id}
                  className="border-b border-gray-700/40 hover:bg-gray-700/20"
                >
                  <td className="py-1.5 pr-3 text-white font-medium">{opp.opponent_name}</td>
                  <td className="py-1.5 pr-3 text-center text-gray-300">{opp.match_count}</td>
                  <td className="py-1.5 pr-3 text-center">
                    <span
                      className={
                        opp.win_rate >= 0.6
                          ? 'text-blue-300 font-semibold'
                          : opp.win_rate <= 0.4
                          ? 'text-red-300'
                          : 'text-gray-300'
                      }
                    >
                      {(opp.win_rate * 100).toFixed(1)}%
                    </span>
                  </td>
                  <td className="py-1.5 text-right text-gray-300">{opp.avg_rally_length.toFixed(1)}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export function OpponentStats({ playerId }: OpponentStatsProps) {
  const { t } = useTranslation()
  return (
    <RoleGuard
      allowedRoles={['analyst', 'coach']}
      fallback={
        <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.restricted')}</div>
      }
    >
      <OpponentTable playerId={playerId} />
    </RoleGuard>
  )
}
