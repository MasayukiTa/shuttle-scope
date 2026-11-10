import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'
import { useResearchBundleSlice } from '@/contexts/ResearchBundleContext'
import { EvidenceBadge } from '@/components/dashboard/EvidenceBadge'
import { ResearchNotice } from '@/components/dashboard/ResearchNotice'
import { useCardTheme } from '@/hooks/useCardTheme'
import { AnalysisFilters } from '@/types'
import { useTranslation } from 'react-i18next'
import { fmtPct as pct } from '@/utils/format'
import { shotLabel } from '@/utils/analysisLabels'

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

// 段階の並びとエンドポイント (表示文言は i18n。コンポーネント内で組み立てる)
const CF_PHASES: CFPhase[] = ['cf1', 'cf2', 'cf3']
const CF_ENDPOINTS: Record<CFPhase, string> = {
  cf1: '/analysis/counterfactual_v2',
  cf2: '/analysis/counterfactual_cf2',
  cf3: '/analysis/counterfactual_cf3',
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

export function CounterfactualV2Card({ playerId, filters }: Props) {
  const { t } = useTranslation()

  const { card, cardInner, textHeading, textSecondary, textMuted, textFaint, loading, isLight } = useCardTheme()
  const [cfPhase, setCfPhase] = useState<CFPhase>('cf1')
  // 内部の段階名 (CF-1 / Bootstrap / IPW / N_eff) は画面に出さず、日本語の説明にする
  const CF_PHASE_CONFIG = useMemo<Record<CFPhase, {
    label: string
    endpoint: string
    description: string
    additionalInfo: string
  }>>(() => ({
    cf1: {
      label: t('auto.CounterfactualV2Card.cf1_label'),
      endpoint: CF_ENDPOINTS.cf1,
      description: t('auto.CounterfactualV2Card.cf1_desc'),
      additionalInfo: t('auto.CounterfactualV2Card.cf1_info'),
    },
    cf2: {
      label: t('auto.CounterfactualV2Card.cf2_label'),
      endpoint: CF_ENDPOINTS.cf2,
      description: t('auto.CounterfactualV2Card.cf2_desc'),
      additionalInfo: t('auto.CounterfactualV2Card.cf2_info'),
    },
    cf3: {
      label: t('auto.CounterfactualV2Card.k2'),
      endpoint: CF_ENDPOINTS.cf3,
      description: t('auto.CounterfactualV2Card.cf3_desc'),
      additionalInfo: t('auto.CounterfactualV2Card.cf3_info'),
    },
  }), [t])
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

  const tabBase = 'text-[10px] px-2 py-1 rounded-ss-sm transition-colors duration-fast'
  const tabActive = isLight ? 'bg-blue-600 text-white' : 'bg-blue-500 text-white'
  const tabInactive = isLight
    ? 'text-gray-500 hover:text-gray-700 hover:bg-gray-100'
    : 'text-gray-500 hover:text-gray-300 hover:bg-gray-700/40'

  return (
    <div className={`${card} rounded-ss-lg shadow-card p-4 space-y-3`}>
      <div className="flex items-center justify-between">
        <h3 className={`text-sm font-semibold ${textHeading}`}>{t('auto.CounterfactualV2Card.k1')}</h3>
        <EvidenceBadge
          tier="research"
          evidenceLevel="exploratory"
          sampleSize={meta?.sample_size}
          recommendationAllowed={false}
        />
      </div>

      {/* CF フェーズ切り替えタブ */}
      <div className="flex items-center gap-1">
        {CF_PHASES.map((phase) => (
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
        caution={meta?.caution ?? t('auto.CounterfactualV2Card.caution_fallback', { desc: phaseConfig.description })}
        assumptions={phaseConfig.description}
        promotionCriteria={t('auto.CounterfactualV2Card.promotion')}
      />

      <p className={`text-[10px] ${textFaint}`}>{phaseConfig.additionalInfo}</p>

      {isLoading ? (
        <p className={`text-sm text-center py-4 ${loading}`}>{t('auto.CounterfactualV2Card.computing', { label: phaseConfig.label })}</p>
      ) : comparisons.length === 0 ? (
        <p className={`text-sm text-center py-4 ${loading}`}>
          {t('auto.CounterfactualV2Card.insufficient')}
        </p>
      ) : (
        <div className="space-y-2">
          <p className={`text-[10px] ${textMuted} ss-num`}>{t('auto.CounterfactualV2Card.usable_contexts', { n: usable })}</p>
          {comparisons.map((comp, i) => (
            <div key={i} className={`${cardInner} rounded-ss-sm px-3 py-2 space-y-1`}>
              <div className="flex items-center justify-between">
                <div className={`text-[11px] ${textSecondary}`}>
                  <span className={`font-medium ${textHeading}`}>{shotLabel(t, comp.actual_shot)}</span>
                  <span className={`mx-1 ${textFaint}`}>→</span>
                  <span className={`font-medium ${comp.max_lift > 0 ? liftColor : textMuted}`}>
                    {comp.best_alternative ? shotLabel(t, comp.best_alternative) : '—'}
                  </span>
                  {comp.max_lift !== 0 && (
                    <span className={`ml-1 ${comp.max_lift > 0 ? liftColor : textMuted}`}>
                      {t('auto.CounterfactualV2Card.lift', { v: `${comp.max_lift > 0 ? '+' : ''}${pct(comp.max_lift)}` })}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-1">
                  {comp.opponent_type_label && (
                    <span className={`text-[9px] px-1 rounded-ss-sm ${isLight ? 'bg-gray-100 text-gray-600' : 'bg-gray-700 text-gray-400'}`}>
                      {OPPONENT_TYPE_LABELS[comp.opponent_type_label] ?? comp.opponent_type_label}
                    </span>
                  )}
                  <span className={`text-[10px] ${textFaint} ss-num`}>{t('auto.CounterfactualV2Card.n_only', { n: comp.actual_n })}</span>
                </div>
              </div>
              <div className={`text-[10px] ${textFaint}`}>
                {t('auto.CounterfactualV2Card.context_label', {
                  phase: SCORE_PHASE_LABELS[comp.context.score_phase] ?? comp.context.score_phase,
                  bucket: RALLY_BUCKET_LABELS[comp.context.rally_bucket] ?? comp.context.rally_bucket,
                  prev: comp.context.prev_shot ? t('auto.CounterfactualV2Card.prev_shot', { shot: shotLabel(t, comp.context.prev_shot) }) : '',
                })}
              </div>
              <div className={`text-[10px] ${textMuted} ss-num`}>
                {t('auto.CounterfactualV2Card.actual_wr', { wr: pct(comp.actual_win_rate) })}
                <span className="ml-1">{t('auto.CounterfactualV2Card.ci_range', { lo: pct(comp.actual_ci_low), hi: pct(comp.actual_ci_high) })}</span>
              </div>
              {comp.alternatives.slice(0, 2).map((alt) => (
                <div key={alt.shot_type} className={`text-[10px] ${textMuted} ml-2 ss-num`}>
                  {t('auto.CounterfactualV2Card.alt_line', { shot: shotLabel(t, alt.shot_type), wr: pct(alt.win_rate), lo: pct(alt.ci_low), hi: pct(alt.ci_high) })}
                  {cfPhase === 'cf2' && alt.ipw_win_rate != null && (
                    <span className={`ml-1 ${isLight ? 'text-blue-600' : 'text-blue-400'}`}>
                      {t('auto.CounterfactualV2Card.ipw', { v: pct(alt.ipw_win_rate) })}
                      {alt.n_eff != null && <span className={textFaint}> {t('auto.CounterfactualV2Card.n_eff', { v: alt.n_eff.toFixed(1) })}</span>}
                    </span>
                  )}
                  <span className={`ml-1 ${alt.overlap_score > 0.5 ? overlapWarnColor : textFaint}`}>
                    {alt.overlap_score > 0.5 && t('auto.CounterfactualV2Card.ci_overlap')}
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
