// 研究タブ bundle 取得フック（optional）
// backend 側の /api/analysis/bundle/research は後続タスクで実装されるため、
// ここでは 404 / 500 / network error を silent fail として undefined を返す。
// これにより backend 未実装でも各カードは従来の個別 fetch にフォールバックして動作する。
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'
import { AnalysisFilters } from '@/types'

// 研究タブが配信対象とする 10 カードのキー
// 将来 backend 側 bundle endpoint と揃える必要あり
export type ResearchBundleKey =
  | 'epv'
  | 'epv_state_table'
  | 'state_action_values'
  | 'counterfactual_shots'
  | 'counterfactual_v2'
  | 'bayes_matchup'
  | 'opponent_policy'
  | 'doubles_role'
  | 'shot_influence_v2'
  | 'hazard_fatigue'

export interface ResearchBundleResponse {
  success: boolean
  data: Partial<Record<ResearchBundleKey, unknown | null>>
  meta?: {
    player_id?: number
    sample_size?: number
    errors?: Record<string, string> | null
  }
}

function toQueryParams(filters?: AnalysisFilters): Record<string, string> {
  if (!filters) return {}
  const p: Record<string, string> = {}
  if (filters.result && filters.result !== 'all') p.result = filters.result
  if (filters.tournamentLevel) p.tournament_level = filters.tournamentLevel
  if (filters.dateFrom) p.date_from = filters.dateFrom
  if (filters.dateTo) p.date_to = filters.dateTo
  return p
}

/**
 * 研究タブ bundle を optional に取得する。
 *
 * backend 未実装 / 404 / 500 / ネットワークエラー時は silent fail し、
 * undefined を返すことで各カードが個別 fetch にフォールバックできるようにする。
 */
export function useResearchBundle(playerId: number, filters?: AnalysisFilters) {
  return useQuery<ResearchBundleResponse | undefined>({
    queryKey: ['research-bundle', playerId, filters],
    queryFn: async () => {
      try {
        const resp = await apiGet<ResearchBundleResponse>('/analysis/bundle/research', {
          player_id: playerId,
          ...toQueryParams(filters),
        })
        return resp
      } catch {
        // 404 / 500 / network error はすべて silent fail
        // → 個別 fetch フォールバックに任せる
        return undefined
      }
    },
    enabled: !!playerId,
    staleTime: 5 * 60 * 1000,
    retry: false,
  })
}
