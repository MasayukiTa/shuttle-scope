import { apiGet, apiPut } from '@/api/client'

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

// ---------------------------------------------------------------------------
// 確認モード（U3 Review）: 保存済みラリーとストロークの実データ閲覧・編集。
//
// F-T003-03 (muse T003 / E-90e8cfaa2891): 確認タブが実データ未接続だった。
// ラリー一覧は既存の `GET /rallies/match/{match_id}` を、ストローク一覧は編集に
// 必要な全フィールドと id を返す `GET /rallies/{rally_id}/strokes` を使う。編集は
// 既存の `PUT /strokes/{stroke_id}` を叩く。権限はいずれも match scope に従う。
// ---------------------------------------------------------------------------

export interface ReviewRally {
  id: number
  uuid: string | null
  set_id: number
  rally_num: number
  server: string
  winner: string
  end_type: string
  rally_length: number
  duration_sec: number | null
  score_a_after: number
  score_b_after: number
  is_deuce: boolean
  video_timestamp_start: number | null
  video_timestamp_end: number | null
}

export interface ReviewStroke {
  id: number
  rally_id: number
  stroke_num: number
  player: string
  shot_type: string
  shot_quality: string | null
  hit_zone: string | null
  land_zone: string | null
  contact_height: string | null
  intent_tag: string | null
  intent_note: string | null
}

interface RallyListResponse {
  success: boolean
  data: ReviewRally[]
}

interface StrokeListResponse {
  success: boolean
  data: { rally_id: number; strokes: ReviewStroke[] }
}

/** 試合の保存済みラリー一覧（確認モード用）。権限は match scope に従う。 */
export async function getMatchRallies(matchId: number): Promise<ReviewRally[]> {
  const res = await apiGet<RallyListResponse>(`/rallies/match/${matchId}`)
  return res.data ?? []
}

/** 指定ラリーの保存済みストローク一覧（編集に必要な id と全フィールドを含む）。 */
export async function getRallyStrokes(rallyId: number): Promise<ReviewStroke[]> {
  const res = await apiGet<StrokeListResponse>(`/rallies/${rallyId}/strokes`)
  return res.data?.strokes ?? []
}

/**
 * 1 ストロークの編集。送った項目だけを更新する（PUT /strokes/{id} は exclude_unset）。
 * stroke_num / player は既存値を必ず送り、サーバの必須バリデーションを満たす。
 */
export async function updateStroke(
  stroke: Pick<ReviewStroke, 'id' | 'stroke_num' | 'player'>,
  patch: Partial<Pick<ReviewStroke,
    'shot_type' | 'land_zone' | 'player' | 'intent_tag' | 'intent_note' | 'contact_height'>>,
): Promise<ReviewStroke> {
  const body = { stroke_num: stroke.stroke_num, player: stroke.player, ...patch }
  const res = await apiPut<{ success: boolean; data: ReviewStroke }>(
    `/strokes/${stroke.id}`,
    body,
  )
  return res.data
}
