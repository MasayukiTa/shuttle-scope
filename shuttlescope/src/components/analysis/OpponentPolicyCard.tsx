import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'
import { EvidenceBadge } from '@/components/dashboard/EvidenceBadge'
import { ResearchNotice } from '@/components/dashboard/ResearchNotice'
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
  policy: PolicyEntry
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
const PREDICTABILITY_COLORS: Record<string, string> = {
  predictable: 'text-amber-400',
  mixed: 'text-gray-400',
  unpredictable: 'text-sky-400',
}

function pct(v: number) {
  return `${(v * 100).toFixed(1)}%`
}

function EntropyBar({ entropy, maxEntropy = 2.5 }: { entropy: number; maxEntropy?: number }) {
  const ratio = Math.min(entropy / maxEntropy, 1)
  return (
    <div className="flex items-center gap-1">
      <div className="w-16 h-1.5 bg-gray-700 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full bg-sky-600"
          style={{ width: `${ratio * 100}%` }}
        />
      </div>
      <span className="text-[10px] text-gray-500">{entropy.toFixed(2)}</span>
    </div>
  )
}

export function OpponentPolicyCard({ playerId, filters }: Props) {
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
  const contexts = (policyData?.context_policies ?? []).slice(0, 8)

  return (
    <div className="bg-gray-800 rounded-lg p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-200">対戦相手ポリシー分析</h3>
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
        <p className="text-gray-500 text-sm text-center py-4">計算中...</p>
      ) : !global ? (
        <p className="text-gray-500 text-sm text-center py-4">対戦ストロークデータが不足しています</p>
      ) : (
        <div className="space-y-3">
          {/* 全体ポリシー */}
          <div className="bg-gray-700/40 rounded px-3 py-2 space-y-1">
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-gray-400">全体ポリシー</span>
              <span className="text-[10px] text-gray-500">N={policyData?.total_strokes ?? 0}</span>
            </div>
            <div className="flex items-center gap-3">
              <div>
                <span className="text-xs text-gray-500">主要ショット: </span>
                <span className="text-white text-xs font-medium">{global.dominant_shot}</span>
                <span className="text-gray-500 text-[10px] ml-1">({pct(global.dominant_freq)})</span>
              </div>
              <div className="flex items-center gap-1">
                <span className="text-xs text-gray-500">予測性:</span>
                <span className={`text-xs font-medium ${PREDICTABILITY_COLORS[global.predictability] ?? 'text-gray-400'}`}>
                  {PREDICTABILITY_LABELS[global.predictability] ?? global.predictability}
                </span>
              </div>
            </div>
            <div className="flex items-center gap-1">
              <span className="text-[10px] text-gray-500">エントロピー:</span>
              <EntropyBar entropy={global.entropy} />
            </div>
          </div>

          {/* コンテキスト別 */}
          {contexts.length > 0 && (
            <div className="space-y-1">
              <p className="text-[10px] text-gray-500">コンテキスト別ポリシー（上位{contexts.length}件）</p>
              {contexts.map((ctx, i) => (
                <div key={i} className="bg-gray-700/20 rounded px-2 py-1.5 flex items-center justify-between">
                  <div className="space-y-0.5">
                    <div className="text-[10px] text-gray-400">
                      {SCORE_PHASE_LABELS[ctx.context.score_phase] ?? ctx.context.score_phase}
                      / {RALLY_BUCKET_LABELS[ctx.context.rally_bucket] ?? ctx.context.rally_bucket}ラリー
                      {ctx.context.zone && ` / ${ctx.context.zone}`}
                    </div>
                    <div className="text-[10px]">
                      <span className="text-white font-medium">{ctx.policy.dominant_shot}</span>
                      <span className="text-gray-500 ml-1">({pct(ctx.policy.dominant_freq)})</span>
                      <span className={`ml-2 ${PREDICTABILITY_COLORS[ctx.policy.predictability] ?? 'text-gray-400'}`}>
                        {PREDICTABILITY_LABELS[ctx.policy.predictability] ?? ctx.policy.predictability}
                      </span>
                    </div>
                  </div>
                  <div className="text-right">
                    <EntropyBar entropy={ctx.policy.entropy} />
                    <span className="text-[10px] text-gray-600">N={ctx.policy.n}</span>
                  </div>
                </div>
              ))}
            </div>
          )}

          <p className="text-[10px] text-gray-600">
            エントロピー高 = ショット選択が多様（予測困難）。エントロピー低 = 特定ショットに集中（予測可能）。
          </p>
        </div>
      )}
    </div>
  )
}
