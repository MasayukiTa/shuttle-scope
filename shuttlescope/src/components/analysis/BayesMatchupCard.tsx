import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'
import { EvidenceBadge } from '@/components/dashboard/EvidenceBadge'
import { ResearchNotice } from '@/components/dashboard/ResearchNotice'
import { AnalysisFilters } from '@/types'

interface OpponentEstimate {
  opponent_id: number
  opponent_name: string
  n_matches: number
  raw_win_rate: number
  posterior_win_prob: number
  credible_interval: [number, number]
  shrinkage_weight: number
  opponent_type: string
}

interface BayesMatchupData {
  global_prior: { alpha: number; beta: number }
  global_win_rate: number
  opponent_estimates: OpponentEstimate[]
  total_matches: number
}

interface Meta {
  tier: string
  evidence_level: string
  sample_size: number
  caution: string | null
}

interface Props {
  playerId: number
  filters: AnalysisFilters
}

const OPPONENT_TYPE_LABELS: Record<string, string> = {
  strong: '強敵',
  weak: '格下',
  neutral: '均衡',
}

function pct(v: number) {
  return `${(v * 100).toFixed(1)}%`
}

export function BayesMatchupCard({ playerId, filters }: Props) {
  const filterApiParams = {
    ...(filters.result !== 'all' ? { result: filters.result } : {}),
    ...(filters.tournamentLevel ? { tournament_level: filters.tournamentLevel } : {}),
    ...(filters.dateFrom ? { date_from: filters.dateFrom } : {}),
    ...(filters.dateTo ? { date_to: filters.dateTo } : {}),
  }

  const { data, isLoading } = useQuery({
    queryKey: ['bayes-matchup', playerId, filters],
    queryFn: () =>
      apiGet<{ success: boolean; data: BayesMatchupData; meta: Meta }>(
        '/analysis/bayes_matchup',
        { player_id: playerId, ...filterApiParams }
      ),
  })

  const meta = data?.meta
  const matchupData = data?.data
  const estimates = (matchupData?.opponent_estimates ?? []).slice(0, 10)

  return (
    <div className="bg-gray-800 rounded-lg p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-200">ベイズ対戦予測（相手別勝率）</h3>
        <EvidenceBadge
          tier="research"
          evidenceLevel="exploratory"
          sampleSize={meta?.sample_size}
          recommendationAllowed={false}
        />
      </div>

      <ResearchNotice
        caution={meta?.caution ?? 'ベイズ対戦予測はBeta-Binomialモデルによる探索的推定です。対戦数が少ない相手ほど事前分布への収縮が強くなります。'}
        assumptions="Beta-Binomial経験的ベイズ。事前分布はモーメント法で推定。各対戦は独立と仮定。"
        promotionCriteria="相手ごとN≥5試合・95%信用区間幅0.4以内"
      />

      {isLoading ? (
        <p className="text-gray-500 text-sm text-center py-4">計算中...</p>
      ) : estimates.length === 0 ? (
        <p className="text-gray-500 text-sm text-center py-4">対戦データが不足しています</p>
      ) : (
        <div className="space-y-1">
          <div className="flex items-center justify-between text-[10px] text-gray-500 pb-1">
            <span>総試合数: {matchupData?.total_matches ?? 0}</span>
            <span>全体勝率: {pct(matchupData?.global_win_rate ?? 0)}</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-500 border-b border-gray-700">
                  <th className="text-left py-1.5 pr-2">相手</th>
                  <th className="text-right py-1.5 pr-2">N</th>
                  <th className="text-right py-1.5 pr-2">生勝率</th>
                  <th className="text-right py-1.5 pr-2">事後勝率</th>
                  <th className="text-right py-1.5">CI [95%]</th>
                </tr>
              </thead>
              <tbody>
                {estimates.map((est, i) => (
                  <tr key={i} className="border-b border-gray-700/40 hover:bg-gray-700/20">
                    <td className="py-1.5 pr-2">
                      <span className="text-white">{est.opponent_name}</span>
                      {est.opponent_type !== 'neutral' && (
                        <span className="ml-1 text-[10px] text-gray-500">
                          ({OPPONENT_TYPE_LABELS[est.opponent_type] ?? est.opponent_type})
                        </span>
                      )}
                    </td>
                    <td className="py-1.5 pr-2 text-right text-gray-400">{est.n_matches}</td>
                    <td className="py-1.5 pr-2 text-right text-gray-400">{pct(est.raw_win_rate)}</td>
                    <td className="py-1.5 pr-2 text-right">
                      <span className={est.posterior_win_prob >= 0.5 ? 'text-emerald-400' : 'text-orange-400'}>
                        {pct(est.posterior_win_prob)}
                      </span>
                    </td>
                    <td className="py-1.5 text-right text-gray-500 text-[10px]">
                      [{pct(est.credible_interval[0])}–{pct(est.credible_interval[1])}]
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-[10px] text-gray-600 pt-1">
            事後勝率 = 事前分布への収縮補正後。CI幅が広い行はサンプル不足で信頼性が低いです。
          </p>
        </div>
      )}
    </div>
  )
}
