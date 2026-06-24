// DR-OPE ポリシー評価 API クライアント
import { apiGet } from '@/api/client'

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
  best_state: { state_key: string; uplift: number } | null
}

export interface PolicyEvalMeta {
  sample_size: number
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
): Promise<PolicyEvalResponse> {
  return apiGet<PolicyEvalResponse>('/analysis/policy_eval', {
    player_id: playerId,
    ...(temp !== undefined ? { temp } : {}),
  })
}
