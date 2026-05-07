import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'
import { useResearchBundleSlice } from '@/contexts/ResearchBundleContext'
import { EvidenceBadge } from '@/components/dashboard/EvidenceBadge'
import { ResearchNotice } from '@/components/dashboard/ResearchNotice'
import { useCardTheme } from '@/hooks/useCardTheme'
import { AnalysisFilters } from '@/types'
import { useTranslation } from 'react-i18next'

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
  const { t } = useTranslation()

  const { card, textHeading, textSecondary, textMuted, textFaint, tableHeader, rowBorder, rowHover, loading, isLight } = useCardTheme()
  const filterApiParams = {
    ...(filters.result !== 'all' ? { result: filters.result } : {}),
    ...(filters.tournamentLevel ? { tournament_level: filters.tournamentLevel } : {}),
    ...(filters.dateFrom ? { date_from: filters.dateFrom } : {}),
    ...(filters.dateTo ? { date_to: filters.dateTo } : {}),
  }

  type Resp = { success: boolean; data: BayesMatchupData; meta: Meta }
  const { slice: bundled, loading: bundleLoading, provided } = useResearchBundleSlice<Resp>('bayes_matchup')
  const indiv = useQuery({
    queryKey: ['bayes-matchup', playerId, filters],
    queryFn: () =>
      apiGet<Resp>(
        '/analysis/bayes_matchup',
        { player_id: playerId, ...filterApiParams }
      ),
    enabled: !!playerId && !provided && !bundleLoading,
  })
  const data = bundled ?? indiv.data
  const isLoading = provided ? bundleLoading : indiv.isLoading

  const meta = data?.meta
  const matchupData = data?.data
  const estimates = (matchupData?.opponent_estimates ?? []).slice(0, 10)

  return (
    <div className={`${card} rounded-lg p-4 space-y-3`}>
      <div className="flex items-center justify-between">
        <h3 className={`text-sm font-semibold ${textHeading}`}>{t('auto.BayesMatchupCard.k1')}</h3>
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
        <p className={`text-sm text-center py-4 ${loading}`}>{t('auto.BayesMatchupCard.k2')}</p>
      ) : estimates.length === 0 ? (
        <p className={`text-sm text-center py-4 ${loading}`}>{t('auto.BayesMatchupCard.k3')}</p>
      ) : (
        <div className="space-y-1">
          <div className={`flex items-center justify-between text-[10px] ${textMuted} pb-1`}>
            <span>総試合数: {matchupData?.total_matches ?? 0}</span>
            <span>全体勝率: {pct(matchupData?.global_win_rate ?? 0)}</span>
          </div>
          {/* モバイル: カードリスト (md 未満)。情報量を維持しつつ縦並び */}
          <ul className="md:hidden space-y-1.5">
            {estimates.map((est, i) => (
              <li key={i} className={`rounded border p-2 ${isLight ? 'border-gray-200 bg-white/40' : 'border-gray-700 bg-gray-800/40'}`}>
                <div className="flex items-baseline justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <span className={`${textHeading} truncate block`} title={est.opponent_name}>{est.opponent_name}</span>
                    {est.opponent_type !== 'neutral' && (
                      <span className={`text-[10px] ${textFaint}`}>
                        {OPPONENT_TYPE_LABELS[est.opponent_type] ?? est.opponent_type}
                      </span>
                    )}
                  </div>
                  <span className={'shrink-0 text-base font-semibold num-cell ' + (est.posterior_win_prob >= 0.5 ? (isLight ? 'text-emerald-600' : 'text-emerald-400') : (isLight ? 'text-orange-600' : 'text-orange-400'))}>
                    {pct(est.posterior_win_prob)}
                  </span>
                </div>
                <div className={`grid grid-cols-3 gap-1 mt-1 text-[10px] ${textFaint} num-cell`}>
                  <span>N={est.n_matches}</span>
                  <span>{t('auto.BayesMatchupCard.k5')} {pct(est.raw_win_rate)}</span>
                  <span className="text-right">CI {pct(est.credible_interval[0])}–{pct(est.credible_interval[1])}</span>
                </div>
              </li>
            ))}
          </ul>

          {/* デスクトップ: テーブル (md 以上) */}
          <div className="hidden md:block overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className={tableHeader}>
                  <th className="text-left py-1.5 pr-2">{t('auto.BayesMatchupCard.k4')}</th>
                  <th className="text-right py-1.5 pr-2">N</th>
                  <th className="text-right py-1.5 pr-2">{t('auto.BayesMatchupCard.k5')}</th>
                  <th className="text-right py-1.5 pr-2">{t('auto.BayesMatchupCard.k6')}</th>
                  <th className="text-right py-1.5">CI [95%]</th>
                </tr>
              </thead>
              <tbody>
                {estimates.map((est, i) => (
                  <tr key={i} className={`${rowBorder} ${rowHover}`}>
                    <td className="py-1.5 pr-2">
                      <span className={`${textHeading} cell-name-clip`} title={est.opponent_name}>{est.opponent_name}</span>
                      {est.opponent_type !== 'neutral' && (
                        <span className={`ml-1 text-[10px] ${textFaint}`}>
                          ({OPPONENT_TYPE_LABELS[est.opponent_type] ?? est.opponent_type})
                        </span>
                      )}
                    </td>
                    <td className={`py-1.5 pr-2 text-right ${textSecondary} num-cell`}>{est.n_matches}</td>
                    <td className={`py-1.5 pr-2 text-right ${textSecondary} num-cell`}>{pct(est.raw_win_rate)}</td>
                    <td className="py-1.5 pr-2 text-right">
                      <span className={'num-cell ' + (est.posterior_win_prob >= 0.5 ? (isLight ? 'text-emerald-600' : 'text-emerald-400') : (isLight ? 'text-orange-600' : 'text-orange-400'))}>
                        {pct(est.posterior_win_prob)}
                      </span>
                    </td>
                    <td className={`py-1.5 text-right text-[10px] ${textFaint} num-cell`}>
                      [{pct(est.credible_interval[0])}–{pct(est.credible_interval[1])}]
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className={`text-[10px] ${textFaint} pt-1`}>
            事後勝率 = 事前分布への収縮補正後。CI幅が広い行はサンプル不足で信頼性が低いです。
          </p>
        </div>
      )}
    </div>
  )
}
