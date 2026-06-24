// コンフォーマル予測 API クライアント（分布フリーカバレッジ保証）
import { apiGet } from '@/api/client'

// ── 型定義 ──────────────────────────────────────────────────────────────────

/** per_group の 1 行 */
export interface ConformalGroup {
  /** "<score_phase>|<role>|<shot_bucket>" の形式 */
  group: string
  /** ラリー勝利確率 (0..1) */
  p_win: number
  /** 予測セット: ["win"] / ["loss"] / ["win","loss"] */
  prediction_set: Array<'win' | 'loss'>
  /** サンプル数 */
  n: number
  /** 勝利数 */
  n_win: number
}

export interface ConformalValidation {
  coverage_guarantee_met: boolean
}

export interface ConformalData {
  /** 有意水準 α (例: 0.1) */
  alpha: number
  /** 目標カバレッジ = 1 - α */
  target_coverage: number
  /** 総サンプル数 */
  n_total: number
  /** 校正サンプル数 */
  n_calibration: number
  /** テストサンプル数 */
  n_test: number
  /** コンフォーマル分位数 */
  conformal_quantile: number
  /** 実測カバレッジ (null = データ不足) */
  empirical_coverage: number | null
  /** 平均予測セットサイズ */
  avg_set_size: number
  /** グループ別予測 */
  per_group: ConformalGroup[]
  /** 保証検証 */
  validation: ConformalValidation
  /** データ不足状態の場合に存在 */
  status?: string
}

export interface ConformalMeta {
  sample_size: number
  confidence: Record<string, unknown>
  analysis_type: string
  tier: string
  evidence_level: string
}

export interface ConformalResponse {
  success: boolean
  data: ConformalData
  meta: ConformalMeta
}

// ── API 関数 ─────────────────────────────────────────────────────────────────

/**
 * コンフォーマル予測分析を取得する（分布フリーカバレッジ保証）。
 *
 * @param playerId - 対象選手 ID
 * @param alpha    - 有意水準 (デフォルト 0.1 → 目標カバレッジ 90%)
 */
export function fetchConformal(
  playerId: number,
  alpha: number = 0.1,
): Promise<ConformalResponse> {
  return apiGet<ConformalResponse>('/analysis/conformal', {
    player_id: playerId,
    alpha,
  })
}
