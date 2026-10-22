// DR-OPE ポリシー評価 API クライアント
import { apiGet } from '@/api/client'
import type { AnalysisFilters, SampleUnit } from '@/types'
import { toFilterApiParams, type FilterScopeMeta } from '@/utils/analysisFilterParams'

// ── 型定義 ──────────────────────────────────────────────────────────────────

/** ok 状態の 1 行 */
export interface PolicyEvalStateOk {
  state_key: string
  status: 'ok'
  n: number
  value_behavior: number
  value_target: number
  uplift: number
  ci_low: number
  ci_high: number
  behavior_policy: Record<string, number>
  target_policy: Record<string, number>
}

/** データ不足状態の 1 行 */
export interface PolicyEvalStateInsufficient {
  state_key: string
  status: 'insufficient'
  n: number
}

export type PolicyEvalState = PolicyEvalStateOk | PolicyEvalStateInsufficient

export interface PolicyEvalSummary {
  states_analyzed: number
  states_insufficient: number
  mean_uplift: number
  /** CI が支持する場合のみ返る (最大 uplift かつ ci_low > value_behavior) */
  best_state: { state_key: string; uplift: number; n: number } | null
  /** 最大点推定の候補。best_state が null のときは不確実として表示する */
  top_candidate: { state_key: string; uplift: number; n: number } | null
}

export interface PolicyEvalMeta extends FilterScopeMeta {
  sample_size: number
  sample_unit?: SampleUnit | null
  confidence: Record<string, unknown>
  analysis_type: 'policy_eval'
  tier: string
  evidence_level: string
}

export interface PolicyEvalResponse {
  success: boolean
  data: {
    states: PolicyEvalState[]
    summary: PolicyEvalSummary
  }
  meta: PolicyEvalMeta
}

// ── API 関数 ─────────────────────────────────────────────────────────────────

/**
 * DR-OPE ポリシー評価を取得する。
 *
 * @param playerId - 対象選手 ID
 * @param temp     - ターゲットポリシーの温度パラメータ（省略可）
 */
export function fetchPolicyEval(
  playerId: number,
  temp?: number,
  filters?: AnalysisFilters,
): Promise<PolicyEvalResponse> {
  return apiGet<PolicyEvalResponse>('/analysis/policy_eval', {
    player_id: playerId,
    ...(temp !== undefined ? { temp } : {}),
    ...(filters ? toFilterApiParams(filters) : {}),
  })
}
