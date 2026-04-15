import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'
import { useResearchBundleSlice } from '@/contexts/ResearchBundleContext'
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
    opponent_type?: string | null
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
    ipw_win_rate?: number
    n_eff?: number
  }[]
  best_alternative: string | null
  max_lift: number
  opponent_type_label?: string
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

type CFPhase = 'cf1' | 'cf2' | 'cf3'

const CF_PHASE_CONFIG: Record<CFPhase, {
  label: string
  endpoint: string
  description: string
  additionalInfo: string
}> = {
  cf1: {
    label: 'CF-1 Bootstrap',
    endpoint: '/analysis/counterfactual_v2',
    description: 'コンテキスト一致 + Bootstrap 500回',
    additionalInfo: 'CI幅で不確実性を確認',
  },
  cf2: {
    label: 'CF-2 IPW',
    endpoint: '/analysis/counterfactual_cf2',
    description: '傾向スコア重み付き（IPW）',
    additionalInfo: '有効サンプル数(N_eff)が少ない行は注意',
  },
  cf3: {
    label: 'CF-3 対戦相手別',
    endpoint: '/analysis/counterfactual_cf3',
    description: '対戦相手タイプ条件付き比較',
    additionalInfo: '強敵/格下/均衡の別に傾向が異なる場合',
  },
}

const SCORE_PHASE_LABELS: Record<string, string> = {
  early: '序盤', mid: '中盤', deuce: 'デュース', endgame: '終盤',
}
const RALLY_BUCKET_LABELS: Record<string, string> = {
  short: '短', medium: '中', long: '長',
}
const OPPONENT_TYPE_LABELS: Record<string, string> = {
  strong: '強敵', weak: '格下', neutral: '均衡', all: '全体',
}

function pct(v: number) {
  return `${(v * 100).toFixed(1)}%`
}

export function CounterfactualV2Card({ playerId, filters }: Props) {
  const { card, cardInner, textHeading, textSecondary, textMuted, textFaint, loading, isLight } = useCardTheme()
  const [cfPhase, setCfPhase] = useState<CFPhase>('cf1')
  const phaseConfig = CF_PHASE_CONFIG[cfPhase]

  const filterApiParams = {
    ...(filters.result !== 'all' ? { result: filters.result } : {}),
    ...(filters.tournamentLevel ? { tournament_level: filters.tournamentLevel } : {}),
    ...(filters.dateFrom ? { date_from: filters.dateFrom } : {}),
    ...(filters.dateTo ? { date_to: filters.dateTo } : {}),
  }

  // bundle は cf1（デフォルト phase）のみ対象。cf2/cf3 は従来通り個別 fetch。
  type Resp = { success: boolean; data: { comparisons: CFComparison[]; total_contexts: number; usable_contexts: number; cf_phase?: string }; meta: Meta }
  const bundleSlice = useResearchBundleSlice<Resp>('counterfactual_v2')
  const useBundle = cfPhase === 'cf1' && bundleSlice.provided
  const indiv = useQuery({
    queryKey: ['counterfactual-v2', cfPhase, playerId, filters],
    queryFn: () =>
      apiGet<Resp>(
        phaseConfig.endpoint,
        { player_id: playerId, ...filterApiParams }
      ),
    enabled: !!playerId && !(useBundle && !bundleSlice.loading && bundleSlice.slice != null),
  })
  const data = (useBundle ? bundleSlice.slice : undefined) ?? indiv.data
  const isLoading = useBundle && bundleSlice.loading ? true : indiv.isLoading

  const meta = data?.meta
  const comparisons = (data?.data?.comparisons ?? []).slice(0, 8)
  const usable = data?.data?.usable_contexts ?? 0
  const liftColor = isLight ? 'text-amber-600' : 'text-amber-400'
  const overlapWarnColor = isLight ? 'text-amber-600' : 'text-yellow-600'

  const tabBase = 'text-[10px] px-2 py-1 rounded transition-colors'
  const tabActive = isLight ? 'bg-blue-600 text-white' : 'bg-blue-500 text-white'
  const tabInactive = isLight
    ? 'text-gray-500 hover:text-gray-700 hover:bg-gray-100'
    : 'text-gray-500 hover:text-gray-300 hover:bg-gray-700/40'

  return (
    <div className={`${card} rounded-lg p-4 space-y-3`}>
      <div className="flex items-center justify-between">
        <h3 className={`text-sm font-semibold ${textHeading}`}>反事実的ショット比較</h3>
        <EvidenceBadge
          tier="research"
          evidenceLevel="exploratory"
          sampleSize={meta?.sample_size}
          recommendationAllowed={false}
        />
      </div>

      {/* CF フェーズ切り替えタブ */}
      <div className="flex items-center gap-1">
        {(Object.keys(CF_PHASE_CONFIG) as CFPhase[]).map((phase) => (
          <button
            key={phase}
            className={`${tabBase} ${cfPhase === phase ? tabActive : tabInactive}`}
            onClick={() => setCfPhase(phase)}
          >
            {CF_PHASE_CONFIG[phase].label}
          </button>
        ))}
      </div>

      <ResearchNotice
        caution={meta?.caution ?? `${phaseConfig.description}。反事実的比較は仮説的シナリオです。`}
        assumptions={phaseConfig.description}
        promotionCriteria="CF-2（IPW）実装済み・CF-3（対戦相手別）実装済み・N≥500コンテキスト"
      />

      <p className={`text-[10px] ${textFaint}`}>{phaseConfig.additionalInfo}</p>

      {isLoading ? (
        <p className={`text-sm text-center py-4 ${loading}`}>計算中（{phaseConfig.label}推定中）...</p>
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
                <div className="flex items-center gap-1">
                  {comp.opponent_type_label && (
                    <span className={`text-[9px] px-1 rounded ${isLight ? 'bg-gray-100 text-gray-600' : 'bg-gray-700 text-gray-400'}`}>
                      {OPPONENT_TYPE_LABELS[comp.opponent_type_label] ?? comp.opponent_type_label}
                    </span>
                  )}
                  <span className={`text-[10px] ${textFaint}`}>N={comp.actual_n}</span>
                </div>
              </div>
              <div className={`text-[10px] ${textFaint}`}>
                {SCORE_PHASE_LABELS[comp.context.score_phase] ?? comp.context.score_phase}
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
                  {cfPhase === 'cf2' && alt.ipw_win_rate != null && (
                    <span className={`ml-1 ${isLight ? 'text-blue-600' : 'text-blue-400'}`}>
                      IPW: {pct(alt.ipw_win_rate)}
                      {alt.n_eff != null && <span className={textFaint}> N_eff={alt.n_eff.toFixed(1)}</span>}
                    </span>
                  )}
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
