import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'
import { EvidenceBadge } from '@/components/dashboard/EvidenceBadge'
import { ResearchNotice } from '@/components/dashboard/ResearchNotice'
import { useCardTheme } from '@/hooks/useCardTheme'
import { AnalysisFilters } from '@/types'

interface PolicyEntry {
  dominant_shot: string
  dominant_freq: number
  entropy: number
  predictability: string
  shot_distribution: Record<string, number>
  n: number
}

interface ContextPolicy {
  context_key: string
  context: {
    score_phase: string
    rally_bucket: string
    zone: string | null
  }
  policy: PolicyEntry | undefined
}

interface OpponentPolicyData {
  global_policy: PolicyEntry
  context_policies: ContextPolicy[]
  total_strokes: number
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
const PREDICTABILITY_LABELS: Record<string, string> = {
  predictable: '予測可能',
  mixed: '混合',
  unpredictable: '予測困難',
}

function getPredictabilityColor(key: string, isLight: boolean): string {
  const map: Record<string, [string, string]> = {
    predictable: ['text-amber-600', 'text-amber-400'],
    mixed: ['text-gray-500', 'text-gray-400'],
    unpredictable: ['text-sky-600', 'text-sky-400'],
  }
  const pair = map[key]
  if (!pair) return isLight ? 'text-gray-500' : 'text-gray-400'
  return isLight ? pair[0] : pair[1]
}

function pct(v: number) {
  return `${(v * 100).toFixed(1)}%`
}

function EntropyBar({ entropy, maxEntropy = 2.5, isLight }: { entropy: number; maxEntropy?: number; isLight: boolean }) {
  const ratio = Math.min(entropy / maxEntropy, 1)
  return (
    <div className="flex items-center gap-1">
      <div className={`w-16 h-1.5 rounded-full overflow-hidden ${isLight ? 'bg-gray-200' : 'bg-gray-700'}`}>
        <div
          className="h-full rounded-full bg-sky-600"
          style={{ width: `${ratio * 100}%` }}
        />
      </div>
      <span className={`text-[10px] ${isLight ? 'text-gray-500' : 'text-gray-500'}`}>{entropy.toFixed(2)}</span>
    </div>
  )
}

export function OpponentPolicyCard({ playerId, filters }: Props) {
  const { card, cardInner, cardInnerAlt, textHeading, textSecondary, textMuted, textFaint, loading, isLight } = useCardTheme()
  const filterApiParams = {
    ...(filters.result !== 'all' ? { result: filters.result } : {}),
    ...(filters.tournamentLevel ? { tournament_level: filters.tournamentLevel } : {}),
    ...(filters.dateFrom ? { date_from: filters.dateFrom } : {}),
    ...(filters.dateTo ? { date_to: filters.dateTo } : {}),
  }

  const { data, isLoading } = useQuery({
    queryKey: ['opponent-policy', playerId, filters],
    queryFn: () =>
      apiGet<{ success: boolean; data: OpponentPolicyData; meta: Meta }>(
        '/analysis/opponent_policy',
        { player_id: playerId, ...filterApiParams }
      ),
  })

  const meta = data?.meta
  const policyData = data?.data
  const global = policyData?.global_policy
  // クラッシュ防止: policy が undefined の行を除外する
  const contexts = (policyData?.context_policies ?? []).filter(ctx => ctx.policy != null).slice(0, 8)

  return (
    <div className={`${card} rounded-lg p-4 space-y-3`}>
      <div className="flex items-center justify-between">
        <h3 className={`text-sm font-semibold ${textHeading}`}>対戦相手ポリシー分析</h3>
        <EvidenceBadge
          tier="research"
          evidenceLevel="exploratory"
          sampleSize={meta?.sample_size}
          recommendationAllowed={false}
        />
      </div>

      <ResearchNotice
        caution={meta?.caution ?? '対戦相手ポリシーはショット分布の記述統計です。戦術的意図の推定は含みません。'}
        assumptions="ショット種別はアノテーションに依存。コンテキストはスコアフェーズ・ラリー長・ゾーンで定義。"
        promotionCriteria="コンテキストごとN≥30ストローク・複数対戦での再現性確認"
      />

      {isLoading ? (
        <p className={`text-sm text-center py-4 ${loading}`}>計算中...</p>
      ) : !global ? (
        <p className={`text-sm text-center py-4 ${loading}`}>対戦ストロークデータが不足しています</p>
      ) : (
        <div className="space-y-3">
          {/* 全体ポリシー */}
          <div className={`${cardInner} rounded px-3 py-2 space-y-1`}>
            <div className="flex items-center justify-between">
              <span className={`text-[11px] ${textSecondary}`}>全体ポリシー</span>
              <span className={`text-[10px] ${textFaint}`}>N={policyData?.total_strokes ?? 0}</span>
            </div>
            <div className="flex items-center gap-3">
              <div>
                <span className={`text-xs ${textMuted}`}>主要ショット: </span>
                <span className={`text-xs font-medium ${textHeading}`}>{global.dominant_shot}</span>
                <span className={`text-[10px] ml-1 ${textFaint}`}>({pct(global.dominant_freq)})</span>
              </div>
              <div className="flex items-center gap-1">
                <span className={`text-xs ${textMuted}`}>予測性:</span>
                <span className={`text-xs font-medium ${getPredictabilityColor(global.predictability, isLight)}`}>
                  {PREDICTABILITY_LABELS[global.predictability] ?? global.predictability}
                </span>
              </div>
            </div>
            <div className="flex items-center gap-1">
              <span className={`text-[10px] ${textMuted}`}>エントロピー:</span>
              <EntropyBar entropy={global.entropy} isLight={isLight} />
            </div>
          </div>

          {/* コンテキスト別 */}
          {contexts.length > 0 && (
            <div className="space-y-1">
              <p className={`text-[10px] ${textMuted}`}>コンテキスト別ポリシー（上位{contexts.length}件）</p>
              {contexts.map((ctx, i) => {
                const policy = ctx.policy!
                return (
                  <div key={i} className={`${cardInnerAlt} rounded px-2 py-1.5 flex items-center justify-between`}>
                    <div className="space-y-0.5">
                      <div className={`text-[10px] ${textSecondary}`}>
                        {SCORE_PHASE_LABELS[ctx.context.score_phase] ?? ctx.context.score_phase}
                        / {RALLY_BUCKET_LABELS[ctx.context.rally_bucket] ?? ctx.context.rally_bucket}ラリー
                        {ctx.context.zone && ` / ${ctx.context.zone}`}
                      </div>
                      <div className="text-[10px]">
                        <span className={`font-medium ${textHeading}`}>{policy.dominant_shot}</span>
                        <span className={`ml-1 ${textFaint}`}>({pct(policy.dominant_freq)})</span>
                        <span className={`ml-2 ${getPredictabilityColor(policy.predictability, isLight)}`}>
                          {PREDICTABILITY_LABELS[policy.predictability] ?? policy.predictability}
                        </span>
                      </div>
                    </div>
                    <div className="text-right">
                      <EntropyBar entropy={policy.entropy} isLight={isLight} />
                      <span className={`text-[10px] ${textFaint}`}>N={policy.n}</span>
                    </div>
                  </div>
                )
              })}
            </div>
          )}

          <p className={`text-[10px] ${textFaint}`}>
            エントロピー高 = ショット選択が多様（予測困難）。エントロピー低 = 特定ショットに集中（予測可能）。
          </p>
        </div>
      )}
    </div>
  )
}
