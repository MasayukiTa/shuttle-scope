import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'
import { useResearchBundleSlice } from '@/contexts/ResearchBundleContext'
import { EvidenceBadge } from '@/components/dashboard/EvidenceBadge'
import { ResearchNotice } from '@/components/dashboard/ResearchNotice'
import { useCardTheme } from '@/hooks/useCardTheme'
import { AnalysisFilters } from '@/types'

interface BestActionRow {
  state: { score_phase: string; set_phase: string; rally_bucket: string; player_role: string }
  best_action: string
  best_q: number
  best_q_ci_low: number
  best_q_ci_high: number
  n_actions: number
  n_reliable_actions: number
}
interface Meta { tier: string; evidence_level: string; sample_size: number; caution: string | null }
interface Props { playerId: number; filters: AnalysisFilters }

const SCORE_PHASE_LABELS: Record<string, string> = { early: '序盤', mid: '中盤', deuce: 'デュース', endgame: '終盤' }
const RALLY_BUCKET_LABELS: Record<string, string> = { short: '短', medium: '中', long: '長' }
const ROLE_LABELS: Record<string, string> = { server: 'Sv', receiver: 'Rv' }

export function StateActionValueCard({ playerId, filters }: Props) {
  const { card, textHeading, textSecondary, textMuted, textFaint, tableHeader, rowBorder, rowHover, loading } = useCardTheme()
  const filterApiParams = {
    ...(filters.result !== 'all' ? { result: filters.result } : {}),
    ...(filters.tournamentLevel ? { tournament_level: filters.tournamentLevel } : {}),
    ...(filters.dateFrom ? { date_from: filters.dateFrom } : {}),
    ...(filters.dateTo ? { date_to: filters.dateTo } : {}),
  }
  type Resp = { success: boolean; data: BestActionRow[]; meta: Meta }
  const { slice: bundled, loading: bundleLoading, provided } = useResearchBundleSlice<Resp>('state_action_values')
  const indiv = useQuery({
    queryKey: ['state-best-actions', playerId, filters],
    queryFn: () => apiGet<Resp>('/analysis/state_best_actions', { player_id: playerId, ...filterApiParams }),
    enabled: !!playerId && !provided && !bundleLoading,
  })
  const data = bundled ?? indiv.data
  const isLoading = provided ? bundleLoading : indiv.isLoading
  const meta = data?.meta
  const rows = (data?.data ?? []).slice(0, 10)

  return (
    <div className={`${card} rounded-lg p-4 space-y-3`}>
      <div className="flex items-center justify-between">
        <h3 className={`text-sm font-semibold ${textHeading}`}>状態-行動価値（Q値）最善手</h3>
        <EvidenceBadge tier="research" evidenceLevel="exploratory" sampleSize={meta?.sample_size} recommendationAllowed={false} />
      </div>
      <ResearchNotice
        caution={meta?.caution ?? '状態-行動価値はサンプル不足で高分散になります。CI幅の広い行は参考程度にとどめてください。'}
        assumptions="行動＝ラリーの最終ショット種別。即時報酬＝ラリー勝率（将来割引なし）。"
        promotionCriteria="状態×行動ごとN≥30・CI幅0.3以内"
      />
      {isLoading ? (
        <p className={`text-sm text-center py-4 ${loading}`}>計算中...</p>
      ) : rows.length === 0 ? (
        <p className={`text-sm text-center py-4 ${loading}`}>十分なデータがありません</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className={tableHeader}>
                <th className="text-left py-1.5 pr-2">状態</th>
                <th className="text-left py-1.5 pr-2">最善ショット</th>
                <th className="text-right py-1.5 pr-2">Q値</th>
                <th className="text-right py-1.5">CI [95%]</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={i} className={`${rowBorder} ${rowHover}`}>
                  <td className={`py-1.5 pr-2 whitespace-nowrap ${textMuted}`}>
                    {SCORE_PHASE_LABELS[row.state.score_phase] ?? row.state.score_phase}
                    /{RALLY_BUCKET_LABELS[row.state.rally_bucket] ?? row.state.rally_bucket}
                    /{ROLE_LABELS[row.state.player_role] ?? row.state.player_role}
                  </td>
                  <td className={`py-1.5 pr-2 font-medium ${textSecondary}`}>{row.best_action}</td>
                  <td className="py-1.5 pr-2 text-right">
                    <span className={row.best_q > 0 ? 'text-emerald-500' : 'text-orange-500'}>
                      {row.best_q > 0 ? '+' : ''}{(row.best_q * 100).toFixed(1)}pp
                    </span>
                  </td>
                  <td className={`py-1.5 text-right text-[10px] ${textFaint}`}>
                    [{(row.best_q_ci_low * 100).toFixed(1)}–{(row.best_q_ci_high * 100).toFixed(1)}]
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className={`text-[10px] ${textFaint}`}>Q値 = 状態内最善ショット勝率 - 状態ベースライン勝率。CI幅が大きい場合は統計的根拠が弱いです。</p>
    </div>
  )
}
