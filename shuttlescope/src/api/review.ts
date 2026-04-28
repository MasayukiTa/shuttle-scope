import { apiGet } from '@/api/client'

export interface PlaylistRally {
  id: number
  set_num: number
  rally_num: number
  server: string
  winner: string
  end_type: string
  rally_length: number
  duration_sec: number | null
  score_a_before: number
  score_b_before: number
  score_a_after: number
  score_b_after: number
  video_timestamp_start: number | null
  video_timestamp_end: number | null
  is_skipped: boolean
}

export interface PlaylistResponse {
  success: boolean
  has_timestamps: boolean
  // Phase 1: 生パスは削除済み。video_token を app://video/{token} で再生する。
  video_token: string | null
  video_url: string | null
  rallies: PlaylistRally[]
}

export interface SummaryCard {
  level: 'warn' | 'info' | 'good'
  title: string
  body: string
}

export interface QuickSummaryResponse {
  success: boolean
  cards: SummaryCard[]
  window: number
  total_rallies: number
}

export function getPlaylist(
  matchId: number,
  opts?: {
    winner?: string
    end_type?: string
    set_num?: number
    has_timestamp_only?: boolean
  },
): Promise<PlaylistResponse> {
  const params = new URLSearchParams({ match_id: String(matchId) })
  if (opts?.winner) params.set('winner', opts.winner)
  if (opts?.end_type) params.set('end_type', opts.end_type)
  if (opts?.set_num != null) params.set('set_num', String(opts.set_num))
  if (opts?.has_timestamp_only) params.set('has_timestamp_only', 'true')
  return apiGet<PlaylistResponse>(`/review/playlist?${params}`)
}

export function getQuickSummary(
  matchId: number,
  asOfSet: number,
  opts?: { asOfRally?: number; playerSide?: string },
): Promise<QuickSummaryResponse> {
  const params = new URLSearchParams({
    match_id: String(matchId),
    as_of_set: String(asOfSet),
  })
  if (opts?.asOfRally != null) params.set('as_of_rally', String(opts.asOfRally))
  if (opts?.playerSide) params.set('player_side', opts.playerSide)
  return apiGet<QuickSummaryResponse>(`/review/quick_summary?${params}`)
}
