// 振り返りタブ bundle 取得フック
// DashboardReviewPage 用の 6 カードを 1 リクエストでまとめて取得する
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'
import { AnalysisFilters } from '@/types'

// bundle が配信するカードのキー（backend/routers/analysis_bundle.py と対応）
export type ReviewBundleKey =
  | 'pre_loss_patterns'
  | 'pre_win_patterns'
  | 'effective_distribution_map'
  | 'received_vulnerability'
  | 'set_comparison'
  | 'rally_sequence_patterns'

export interface ReviewBundleResponse {
  success: boolean
  data: Record<ReviewBundleKey, unknown | null>
  meta: { player_id: number; sample_size: number; errors: Record<string, string> | null }
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

export function useReviewBundle(playerId: number, filters?: AnalysisFilters) {
  return useQuery({
    queryKey: ['review-bundle', playerId, filters],
    queryFn: () =>
      apiGet<ReviewBundleResponse>('/analysis/bundle/review', {
        player_id: playerId,
        ...toQueryParams(filters),
      }),
    enabled: !!playerId,
    staleTime: 5 * 60 * 1000, // 5 分
  })
}
