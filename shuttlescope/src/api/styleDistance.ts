// スタイル距離（最適輸送）API クライアント
import { apiGet } from '@/api/client'
import type { AnalysisFilters, SampleUnit } from '@/types'
import { toFilterApiParams, type FilterScopeMeta } from '@/utils/analysisFilterParams'

// ── 型定義 ──────────────────────────────────────────────────────────────────

export interface StyleDistanceEntry {
  player_id: number
  player_name: string
  distance: number
}

export interface StyleMapEntry {
  player_id: number
  player_name: string
  x: number
  y: number
}

export interface StyleDistanceData {
  reference_player: number
  cohort_size: number
  /** 9 ゾーンのラベル */
  zone_labels: string[]
  /** 対象選手に対するコーホート全選手の距離一覧 */
  distances: StyleDistanceEntry[]
  /** 最近傍選手 ID (距離小順) */
  nearest: number[]
  /** 2D スキャタ用座標 */
  style_map: StyleMapEntry[]
}

export interface StyleDistanceMeta extends FilterScopeMeta {
  sample_size: number
  sample_unit?: SampleUnit | null
  confidence: Record<string, unknown>
  analysis_type: 'style_distance'
  tier: string
  evidence_level: string
}

export interface StyleDistanceResponse {
  success: boolean
  data: StyleDistanceData
  meta: StyleDistanceMeta
}

// ── API 関数 ─────────────────────────────────────────────────────────────────

/**
 * スタイル距離（最適輸送）分析を取得する。
 *
 * @param playerId - 対象選手 ID
 */
export function fetchStyleDistance(
  playerId: number,
  filters?: AnalysisFilters,
): Promise<StyleDistanceResponse> {
  return apiGet<StyleDistanceResponse>('/analysis/style_distance', {
    player_id: playerId,
    ...(filters ? toFilterApiParams(filters) : {}),
  })
}
