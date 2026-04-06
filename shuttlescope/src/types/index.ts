// ShuttleScope 共通型定義

/** 解析フィルター（全解析コンポーネントで共有） */
export interface AnalysisFilters {
  result: 'all' | 'win' | 'loss'
  tournamentLevel: string | null
  dateFrom: string | null
  dateTo: string | null
}

export const DEFAULT_FILTERS: AnalysisFilters = {
  result: 'all',
  tournamentLevel: null,
  dateFrom: null,
  dateTo: null,
}

export type UserRole = 'analyst' | 'coach' | 'player'

export type DominantHand = 'R' | 'L'

export type MatchFormat = 'singles' | 'womens_doubles' | 'mixed_doubles'

export type MatchResult = 'win' | 'loss' | 'walkover' | 'unfinished'

export type AnnotationStatus = 'pending' | 'in_progress' | 'complete' | 'reviewed'

export type RallyWinner = 'player_a' | 'player_b'

export type EndType = 'ace' | 'forced_error' | 'unforced_error' | 'net' | 'out' | 'cant_reach'

export type ShotQuality = 'excellent' | 'good' | 'neutral' | 'poor'

export type TournamentLevel = 'IC' | 'IS' | 'SJL' | '全日本' | '国内' | 'その他'

/**
 * 試合のラウンド選択肢（Best XX 表記で統一）
 * ドロー規模に依らず大会内での位置が明確になるよう国際標準に準拠。
 * フォームの選択肢・デフォルト値・フィルター等すべてこの定数から参照すること。
 */
export const MATCH_ROUNDS = [
  '予選（グループリーグ含む）',
  'Best 64',
  'Best 32',
  'Best 16',
  'Best 8（準々決勝）',
  'Best 4（準決勝）',
  '決勝',
] as const

export type MatchRound = typeof MATCH_ROUNDS[number]

export type Zone9 = 'BL' | 'BC' | 'BR' | 'ML' | 'MC' | 'MR' | 'NL' | 'NC' | 'NR'

export type ShotType =
  | 'short_service' | 'long_service' | 'net_shot' | 'clear'
  | 'push_rush' | 'smash' | 'defensive' | 'drive' | 'lob' | 'drop'
  | 'cross_net' | 'slice' | 'around_head' | 'cant_reach'
  | 'flick' | 'half_smash' | 'block' | 'other'

export interface Player {
  id: number
  name: string
  name_en?: string
  team?: string
  nationality?: string
  dominant_hand: DominantHand
  birth_year?: number
  world_ranking?: number
  is_target: boolean
  match_count?: number
  notes?: string
  created_at: string
}

export interface Match {
  id: number
  tournament: string
  tournament_level: TournamentLevel
  tournament_grade?: string
  round: string
  date: string
  venue?: string
  format: MatchFormat
  player_a_id: number
  player_b_id: number
  partner_a_id?: number
  partner_b_id?: number
  result: MatchResult
  final_score?: string
  video_url?: string
  video_local_path?: string
  video_quality?: string
  camera_angle?: string
  annotator_id?: number
  annotation_status: AnnotationStatus
  annotation_progress: number
  notes?: string
  created_at: string
  updated_at: string
  // リレーション（フロント側で結合）
  player_a?: Player
  player_b?: Player
}

export interface GameSet {
  id: number
  match_id: number
  set_num: number
  winner: RallyWinner
  score_a: number
  score_b: number
  duration_min?: number
  is_deuce: boolean
}

export interface Rally {
  id: number
  set_id: number
  rally_num: number
  server: RallyWinner
  winner: RallyWinner
  end_type: EndType
  rally_length: number
  duration_sec?: number
  score_a_after: number
  score_b_after: number
  is_deuce: boolean
  video_timestamp_start?: number
  video_timestamp_end?: number
  strokes?: Stroke[]
}

export interface Stroke {
  id: number
  rally_id: number
  stroke_num: number
  player: string
  shot_type: ShotType
  shot_quality?: ShotQuality
  hit_x?: number
  hit_y?: number
  land_x?: number
  land_y?: number
  player_x?: number
  player_y?: number
  opponent_x?: number
  opponent_y?: number
  hit_zone?: Zone9
  land_zone?: Zone9
  is_backhand: boolean
  is_around_head: boolean
  above_net?: boolean
  is_cross: boolean
  timestamp_sec?: number
  epv?: number
  shot_influence?: number
}

// アノテーション入力用（IDなし）
export interface StrokeInput {
  stroke_num: number
  player: string
  shot_type: ShotType
  hit_zone?: Zone9
  land_zone?: Zone9
  is_backhand: boolean
  is_around_head: boolean
  above_net?: boolean
  timestamp_sec?: number
}

export interface StrokeAttributes {
  is_backhand: boolean
  is_around_head: boolean
  above_net?: boolean
}

// APIレスポンス共通形式
export interface ApiResponse<T> {
  success: boolean
  data: T
  meta?: {
    sample_size?: number
    confidence?: {
      stars: string
      label: string
    }
    computed_at?: string
  }
}

export interface ApiError {
  success: false
  error: {
    code: string
    message: string
    detail?: string
  }
}

export interface User {
  id: number
  username: string
  role: UserRole
  player_id?: number
  created_at: string
}

// ダウンロード進捗
export interface DownloadProgress {
  status: 'pending' | 'downloading' | 'complete' | 'error' | 'unknown'
  percent?: string
  speed?: string
  eta?: string
  filepath?: string
  error?: string
}
