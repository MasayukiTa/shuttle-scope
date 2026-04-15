import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'
import { useAuth } from '@/hooks/useAuth'

// Phase 3: 体調タブ 解析サブタブ向け API フック
// backend 並行実装中のため、エラーは無視して UI は空表示にフォールバック可能にする。

export interface CorrelationPoint {
  x: number
  y: number
  date?: string
  match_id?: number | null
}

export interface CorrelationResponse {
  points: CorrelationPoint[]
  pearson_r: number | null
  n: number
  p_value: number | null
  confidence_note?: string | null
}

export interface BestProfileKeyFactor {
  key: string
  min?: number | null
  max?: number | null
  mean?: number | null
  importance?: number | null
}

export interface BestProfileResponse {
  profile: Record<string, { min: number | null; max: number | null; mean: number | null }>
  win_rate_in_profile: number | null
  win_rate_outside: number | null
  n_matches: number
  confidence?: string | null
  key_factors: BestProfileKeyFactor[]
}

export interface DiscrepancyItem {
  condition_id: number
  date: string
  type: string
  severity: 'low' | 'medium' | 'high'
  detail?: string | null
}

export interface GrowthCard {
  when_key: string
  effect?: string | null
  sample_n: number
  confidence_label?: string | null
}

export interface InsightsResponse {
  growth_cards: GrowthCard[]
  personal_trend?: { ccs_28ma?: number | null; direction?: 'up' | 'flat' | 'down' | null } | null
  // coach/analyst only
  raw_factor_trends?: Array<{ factor: string; series: Array<{ date: string; value: number }> }> | null
  validity_summary?: { valid_ratio?: number | null; flags?: string[] | null } | null
}

export function useCorrelation(
  playerId: number | null,
  x: string | null,
  y: string | null,
  since?: string,
) {
  const { role } = useAuth()
  return useQuery({
    queryKey: ['condition-correlation', playerId, x, y, since],
    queryFn: () => {
      const params: Record<string, string | number> = { player_id: playerId! }
      if (x) params.x = x
      if (y) params.y = y
      if (since) params.since = since
      return apiGet<CorrelationResponse>('/conditions/correlation', params)
    },
    enabled: !!playerId && !!x && !!y && role !== 'player',
    retry: 0,
  })
}

export function useBestProfile(playerId: number | null) {
  return useQuery({
    queryKey: ['condition-best-profile', playerId],
    queryFn: () =>
      apiGet<BestProfileResponse>('/conditions/best_profile', { player_id: playerId! }),
    enabled: !!playerId,
    retry: 0,
  })
}

export function useDiscrepancy(playerId: number | null, limit = 50) {
  const { role } = useAuth()
  return useQuery({
    queryKey: ['condition-discrepancy', playerId, limit],
    queryFn: async (): Promise<DiscrepancyItem[]> => {
      // backend は配列を直接返す場合と {success, data:[...]} 形式の場合があり得るため正規化
      const resp = await apiGet<DiscrepancyItem[] | { success?: boolean; data?: DiscrepancyItem[] }>(
        '/conditions/discrepancy',
        { player_id: playerId!, limit },
      )
      if (Array.isArray(resp)) return resp
      const data = (resp as { data?: DiscrepancyItem[] })?.data
      return Array.isArray(data) ? data : []
    },
    // player には絶対に取得させない（ボタンも非表示）
    enabled: !!playerId && (role === 'coach' || role === 'analyst'),
    retry: 0,
  })
}

export function useInsights(playerId: number | null) {
  return useQuery({
    queryKey: ['condition-insights', playerId],
    queryFn: () =>
      apiGet<InsightsResponse>('/conditions/insights', { player_id: playerId! }),
    enabled: !!playerId,
    retry: 0,
  })
}
