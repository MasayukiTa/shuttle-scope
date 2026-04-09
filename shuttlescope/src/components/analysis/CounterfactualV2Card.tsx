import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'
import { EvidenceBadge } from '@/components/dashboard/EvidenceBadge'
import { ResearchNotice } from '@/components/dashboard/ResearchNotice'
import { useCardTheme } from '@/hooks/useCardTheme'
import { AnalysisFilters } from '@/types'

interface CFComparison {
  context_key: string
  context: {
    score_phase: string
    rally_bucket: string
    set_phase: string
    prev_shot: string | null
  }
  actual_shot: string
  actual_win_rate: number
  actual_n: number
  actual_ci_low: number
  actual_ci_high: number
  alternatives: {
    shot_type: string
    win_rate: number
    n: number
    ci_low: number
    ci_high: number
    estimated_lift: number
    overlap_score: number
  }[]
  best_alternative: string | null
  max_lift: number
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

const SCORE_PHASE_LABELS: Record<string, string> = {
  early: '序盤', mid: '中盤', deuce: 'デュース', endgame: '終盤',
}
const RALLY_BUCKET_LABELS: Record<string, string> = {
  short: '短', medium: '中', long: '長',
}

function pct(v: number) {
  return `${(v * 100).toFixed(1)}%`
}

export function CounterfactualV2Card({ playerId, filters }: Props) {
  const { card, cardInner, textHeading, textSecondary, textMuted, textFaint, loading, isLight } = useCardTheme()
  const filterApiParams = {
    ...(filters.result !== 'all' ? { result: filters.result } : {}),
    ...(filters.tournamentLevel ? { tournament_level: filters.tournamentLevel } : {}),
    ...(filters.dateFrom ? { date_from: filters.dateFrom } : {}),
    ...(filters.dateTo ? { date_to: filters.dateTo } : {}),
  }

  const { data, isLoading } = useQuery({
    queryKey: ['counterfactual-v2', playerId, filters],
    queryFn: () =>
      apiGet<{ success: boolean; data: { comparisons: CFComparison[]; total_contexts: number; usable_contexts: number }; meta: Meta }>(
        '/analysis/counterfactual_v2',
        { player_id: playerId, ...filterApiParams }
      ),
  })

  const meta = data?.meta
  const comparisons = (data?.data?.comparisons ?? []).slice(0, 8)
  const usable = data?.data?.usable_contexts ?? 0
  const liftColor = isLight ? 'text-amber-600' : 'text-amber-400'
  const overlapWarnColor = isLight ? 'text-amber-600' : 'text-yellow-600'

  return (
    <div className={`${card} rounded-lg p-4 space-y-3`}>
      <div className="flex items-center justify-between">
        <h3 className={`text-sm font-semibold ${textHeading}`}>反事実的ショット比較 v2 (Bootstrap CI)</h3>
        <EvidenceBadge
          tier="research"
          evidenceLevel="exploratory"
          sampleSize={meta?.sample_size}
          recommendationAllowed={false}
        />
      </div>

      <ResearchNotice
        caution={meta?.caution ?? '反事実的比較は仮説的シナリオです。交絡制御は未実装（CF-1フェーズ）です。'}
        assumptions="コンテキスト一致（スコアフェーズ・ラリー長・セットフェーズ・前のショット）。ブートストラップ500回。"
        promotionCriteria="傾向スコア重み付け（CF-2）・N≥500コンテキスト"
      />

      {isLoading ? (
        <p className={`text-sm text-center py-4 ${loading}`}>計算中（ブートストラップ推定中）...</p>
      ) : comparisons.length === 0 ? (
        <p className={`text-sm text-center py-4 ${loading}`}>
          十分なデータがありません（各コンテキストで最低10件以上が必要です）
        </p>
      ) : (
        <div className="space-y-2">
          <p className={`text-[10px] ${textMuted}`}>有効コンテキスト: {usable}件（lift 降順上位表示）</p>
          {comparisons.map((comp, i) => (
            <div key={i} className={`${cardInner} rounded px-3 py-2 space-y-1`}>
              <div className="flex items-center justify-between">
                <div className={`text-[11px] ${textSecondary}`}>
                  <span className={`font-medium ${textHeading}`}>{comp.actual_shot}</span>
                  <span className={`mx-1 ${textFaint}`}>→</span>
                  <span className={`font-medium ${comp.max_lift > 0 ? liftColor : textMuted}`}>
                    {comp.best_alternative ?? '—'}
                  </span>
                  {comp.max_lift !== 0 && (
                    <span className={`ml-1 ${comp.max_lift > 0 ? liftColor : textMuted}`}>
                      ({comp.max_lift > 0 ? '+' : ''}{pct(comp.max_lift)} lift)
                    </span>
                  )}
                </div>
                <span className={`text-[10px] ${textFaint}`}>N={comp.actual_n}</span>
              </div>
              <div className={`text-[10px] ${textFaint}`}>
                コンテキスト: {SCORE_PHASE_LABELS[comp.context.score_phase] ?? comp.context.score_phase}
                / {RALLY_BUCKET_LABELS[comp.context.rally_bucket] ?? comp.context.rally_bucket}ラリー
                {comp.context.prev_shot && ` / 直前: ${comp.context.prev_shot}`}
              </div>
              <div className={`text-[10px] ${textMuted}`}>
                実際の勝率: {pct(comp.actual_win_rate)}
                <span className="ml-1">[CI: {pct(comp.actual_ci_low)}–{pct(comp.actual_ci_high)}]</span>
              </div>
              {comp.alternatives.slice(0, 2).map((alt) => (
                <div key={alt.shot_type} className={`text-[10px] ${textMuted} ml-2`}>
                  代替 {alt.shot_type}: {pct(alt.win_rate)} [CI: {pct(alt.ci_low)}–{pct(alt.ci_high)}]
                  <span className={`ml-1 ${alt.overlap_score > 0.5 ? overlapWarnColor : textFaint}`}>
                    {alt.overlap_score > 0.5 && '(CI重複大・不確実)'}
                  </span>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
