// 画面上部の絞り込み (結果・大会レベル・期間) を、解析 API の query に変換する 1 か所。
// backend の MatchFilter (backend/analysis/match_filter.py) と query 名が同じ。
import type { AnalysisFilters } from '@/types'

export interface FilterApiParams {
  result?: 'win' | 'loss'
  tournament_level?: string
  date_from?: string
  date_to?: string
}

export function toFilterApiParams(filters: AnalysisFilters): FilterApiParams {
  return {
    ...(filters.result !== 'all' ? { result: filters.result } : {}),
    ...(filters.tournamentLevel ? { tournament_level: filters.tournamentLevel } : {}),
    ...(filters.dateFrom ? { date_from: filters.dateFrom } : {}),
    ...(filters.dateTo ? { date_to: filters.dateTo } : {}),
  }
}

/** backend の meta.population / meta.filter_scope (stamps_population が書く)。 */
export interface FilterScopeMeta {
  filter_scope?: 'filtered' | 'global_only' | 'not_wired'
  population?: {
    n_matches: number | null
    n_rallies: number | null
    filter_applied: boolean
  }
}
