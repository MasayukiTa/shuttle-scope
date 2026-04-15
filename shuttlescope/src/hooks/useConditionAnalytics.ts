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

// backend は {success, data} ラッパで返すケースと裸で返すケースがあるため正規化
function unwrap<T>(resp: unknown): T {
  if (resp && typeof resp === 'object' && 'data' in (resp as Record<string, unknown>)) {
    const r = resp as { success?: boolean; data?: T }
    if (r.data !== undefined) return r.data as T
  }
  return resp as T
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
    queryFn: async () => {
      const params: Record<string, string | number> = { player_id: playerId! }
      if (x) params.x = x
      if (y) params.y = y
      if (since) params.since = since
      const resp = await apiGet<CorrelationResponse | { data: CorrelationResponse }>(
        '/conditions/correlation',
        params,
      )
      return unwrap<CorrelationResponse>(resp)
    },
    enabled: !!playerId && !!x && !!y && role !== 'player',
    retry: 0,
  })
}

// backend 実体: { key_factors:[{key, effect_size, direction}], top_profile:{[k]:{mean,std,min,max}}, rest_profile, n_top, n_rest, confidence, note }
interface BestProfileRaw {
  key_factors?: Array<{ key: string; effect_size?: number; direction?: string }>
  top_profile?: Record<string, { mean?: number | null; min?: number | null; max?: number | null }>
  rest_profile?: Record<string, { mean?: number | null; min?: number | null; max?: number | null }>
  n_top?: number
  n_rest?: number
  confidence?: string
  note?: string | null
  // 旧形式との互換
  win_rate_in_profile?: number | null
  win_rate_outside?: number | null
  n_matches?: number
  profile?: BestProfileResponse['profile']
}

export function useBestProfile(playerId: number | null) {
  return useQuery({
    queryKey: ['condition-best-profile', playerId],
    queryFn: async (): Promise<BestProfileResponse> => {
      const resp = await apiGet<BestProfileRaw | { data: BestProfileRaw }>(
        '/conditions/best_profile',
        { player_id: playerId! },
      )
      const raw = unwrap<BestProfileRaw>(resp)
      // backend の top_profile レンジを key_factors に合流させて UI 期待形状に正規化
      const top = raw.top_profile ?? {}
      const keyFactors: BestProfileKeyFactor[] = (raw.key_factors ?? []).map((f) => {
        const p = top[f.key] ?? {}
        return {
          key: f.key,
          mean: p.mean ?? null,
          min: p.min ?? null,
          max: p.max ?? null,
          importance: f.effect_size ?? null,
        }
      })
      const profile: BestProfileResponse['profile'] = {}
      for (const [k, v] of Object.entries(top)) {
        profile[k] = { mean: v.mean ?? null, min: v.min ?? null, max: v.max ?? null }
      }
      const nMatches = raw.n_matches ?? (raw.n_top ?? 0) + (raw.n_rest ?? 0)
      return {
        profile: raw.profile ?? profile,
        win_rate_in_profile: raw.win_rate_in_profile ?? null,
        win_rate_outside: raw.win_rate_outside ?? null,
        n_matches: nMatches,
        confidence: raw.confidence ?? null,
        key_factors: keyFactors,
      }
    },
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
    queryFn: async () => {
      const resp = await apiGet<InsightsResponse | { data: InsightsResponse }>(
        '/conditions/insights',
        { player_id: playerId! },
      )
      return unwrap<InsightsResponse>(resp)
    },
    enabled: !!playerId,
    retry: 0,
  })
}
