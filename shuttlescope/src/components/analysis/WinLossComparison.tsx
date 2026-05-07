// 勝ち試合と課題のある試合の主要統計を2カラムで比較するコンポーネント（アナリスト・コーチ向け）
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { RoleGuard } from '@/components/common/RoleGuard'
import { AnalysisFilters, DEFAULT_FILTERS } from '@/types'
import { WIN, LOSS } from '@/styles/colors'

interface WinLossComparisonProps {
  playerId: number
  filters?: AnalysisFilters
}

interface MatchStats {
  count: number
  avg_rally_length: number
  ace_rate: number
  error_rate: number
  serve_win_rate: number
  top_shots: { shot_type: string; shot_type_ja: string; count: number }[]
}

interface WinLossResponse {
  success: boolean
  data: {
    win_matches: MatchStats | null
    loss_matches: MatchStats | null
  }
  meta: {
    sample_size: number
    confidence: { level: string; stars: string; label: string; warning?: string }
  }
}

function StatRow({ label, winVal, lossVal }: { label: string; winVal: string; lossVal: string }) {
  return (
    <tr className="border-b border-gray-700/50">
      <td className="py-2 text-gray-400 text-sm">{label}</td>
      <td className="py-2 text-center font-semibold text-sm num-cell" style={{ color: WIN }}>{winVal}</td>
      <td className="py-2 text-center font-semibold text-sm num-cell" style={{ color: LOSS }}>{lossVal}</td>
    </tr>
  )
}

function ComparisonContent({ playerId, filters = DEFAULT_FILTERS }: { playerId: number; filters?: AnalysisFilters }) {
  const { t } = useTranslation()

  const fp = {
    ...(filters.result !== 'all' ? { result: filters.result } : {}),
    ...(filters.tournamentLevel ? { tournament_level: filters.tournamentLevel } : {}),
    ...(filters.dateFrom ? { date_from: filters.dateFrom } : {}),
    ...(filters.dateTo ? { date_to: filters.dateTo } : {}),
  }
  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-win-loss-comparison', playerId, filters],
    queryFn: () =>
      apiGet<WinLossResponse>('/analysis/win_loss_comparison', { player_id: playerId, ...fp }),
    enabled: !!playerId,
  })

  if (isLoading) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.loading')}</div>
  }

  const sampleSize = resp?.meta?.sample_size ?? 0
  const winStats = resp?.data?.win_matches
  const lossStats = resp?.data?.loss_matches

  if (!winStats && !lossStats) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.no_data')}</div>
  }

  const pct = (v?: number) => v != null ? `${(v * 100).toFixed(1)}%` : '—'
  const num = (v?: number) => v != null ? v.toFixed(1) : '—'

  return (
    <div className="space-y-3">
      <ConfidenceBadge sampleSize={sampleSize} />

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-300 border-b border-gray-600">
              <th className="text-left py-2 pr-4 font-medium text-gray-400">{t('auto.WinLossComparison.k1')}</th>
              <th className="text-center py-2 pr-4 font-medium" style={{ color: WIN }}>
                {t('analysis.win_loss_comparison.win_matches')} ({winStats?.count ?? 0}試合)
              </th>
              <th className="text-center py-2 font-medium" style={{ color: LOSS }}>
                {t('analysis.win_loss_comparison.loss_matches')} ({lossStats?.count ?? 0}試合)
              </th>
            </tr>
          </thead>
          <tbody>
            <StatRow
              label={t('analysis.win_loss_comparison.avg_rally')}
              winVal={num(winStats?.avg_rally_length)}
              lossVal={num(lossStats?.avg_rally_length)}
            />
            <StatRow
              label={t('analysis.win_loss_comparison.serve_win_rate')}
              winVal={pct(winStats?.serve_win_rate)}
              lossVal={pct(lossStats?.serve_win_rate)}
            />
          </tbody>
        </table>
      </div>

      {/* トップショット比較 */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <p className="text-xs mb-2" style={{ color: WIN }}>{t('analysis.win_loss_comparison.win_matches')} {t('analysis.win_loss_comparison.top_shots')}</p>
          <div className="space-y-1">
            {(winStats?.top_shots ?? []).slice(0, 3).map((s) => (
              <div key={s.shot_type} className="text-xs text-gray-300">
                {s.shot_type_ja}: {s.count}
              </div>
            ))}
            {!winStats && <p className="text-xs text-gray-500">—</p>}
          </div>
        </div>
        <div>
          <p className="text-xs mb-2" style={{ color: LOSS }}>{t('analysis.win_loss_comparison.loss_matches')} {t('analysis.win_loss_comparison.top_shots')}</p>
          <div className="space-y-1">
            {(lossStats?.top_shots ?? []).slice(0, 3).map((s) => (
              <div key={s.shot_type} className="text-xs text-gray-300">
                {s.shot_type_ja}: {s.count}
              </div>
            ))}
            {!lossStats && <p className="text-xs text-gray-500">—</p>}
          </div>
        </div>
      </div>
    </div>
  )
}

export function WinLossComparison({ playerId, filters }: WinLossComparisonProps) {
  const { t } = useTranslation()
  return (
    <RoleGuard
      allowedRoles={['analyst', 'coach']}
      fallback={
        <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.restricted')}</div>
      }
    >
      <ComparisonContent playerId={playerId} filters={filters} />
    </RoleGuard>
  )
}
