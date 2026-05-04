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

export type UserRole = 'admin' | 'analyst' | 'coach' | 'player'

export type DominantHand = 'R' | 'L' | 'unknown'

export type ProfileStatus = 'provisional' | 'partial' | 'verified'

export type CompetitionType = 'official' | 'practice_match' | 'open_practice' | 'unknown'

export type MetadataStatus = 'minimal' | 'partial' | 'verified'

export type MatchFormat = 'singles' | 'womens_doubles' | 'mixed_doubles'

export type MatchResult = 'win' | 'loss' | 'walkover' | 'unfinished' | 'retired'

/** 途中終了の理由 */
export type ExceptionReason = 'retired_a' | 'retired_b' | 'abandoned' | null

export type AnnotationStatus = 'pending' | 'in_progress' | 'complete' | 'reviewed'

export type RallyWinner = 'player_a' | 'player_b'

export type EndType = 'ace' | 'forced_error' | 'unforced_error' | 'net' | 'out' | 'cant_reach' | 'skipped'

/** 映像ソースモード */
export type VideoSourceMode = 'local' | 'webview' | 'none'

/** Electronディスプレイ情報 */
export interface DisplayInfo {
  id: number
  label: string
  isPrimary: boolean
  bounds: { x: number; y: number; width: number; height: number }
}

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

/** コート外アウトゾーン (Out of Bounds)
 *  OB_B* = バック外、OB_L* = 左サイド外、OB_R* = 右サイド外、OB_F* = ネット前
 */
export type ZoneOOB =
  | 'OB_BL' | 'OB_BC' | 'OB_BR'   // バックライン外（B=Back, L/C/R）
  | 'OB_LL' | 'OB_LM' | 'OB_LN'   // 左サイドライン外（B/M/N 行）
  | 'OB_RL' | 'OB_RM' | 'OB_RN'   // 右サイドライン外
  | 'OB_FL' | 'OB_FR'              // ネット前（ショートサービスライン内に落下）

/** ネット接触ゾーン（NL/NC/NR境界線上のネットテープ位置） */
export type ZoneNet = 'NET_L' | 'NET_C' | 'NET_R'

/** 落点ゾーン = コート内9マス + コート外11マス + ネット接触3マス */
export type LandZone = Zone9 | ZoneOOB | ZoneNet

export type ShotType =
  | 'short_service' | 'long_service' | 'net_shot' | 'clear'
  | 'push_rush' | 'smash' | 'defensive' | 'drive' | 'lob' | 'drop'
  | 'cross_net' | 'slice' | 'around_head' | 'cant_reach'
  | 'flick' | 'half_smash' | 'block' | 'other'

export interface TeamHistoryEntry {
  team: string
  until?: string   // "2025-03" など任意文字列
  note?: string
}

export interface Player {
  id: number
  name: string
  name_en?: string
  team?: string
  nationality?: string
  dominant_hand?: DominantHand | null
  birth_year?: number
  world_ranking?: number
  is_target: boolean
  match_count?: number
  notes?: string
  created_at: string
  // V4: プロフィール確定度・暫定作成管理
  profile_status?: ProfileStatus
  needs_review?: boolean
  created_via_quick_start?: boolean
  organization?: string
  aliases?: string[]
  name_normalized?: string
  scouting_notes?: string
  // 所属履歴
  team_history?: TeamHistoryEntry[]
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
  /** @deprecated Phase 1 で API レスポンスから除去済み。書き込み時のみ使用（PUT 時に video_token が自動発行される）。 */
  video_local_path?: string
  /** バックエンドが発行する不透明トークン。再生は app://video/{video_token} で行う。 */
  video_token?: string
  /** ローカル動画のファイル名（パスは含まない、表示用）。 */
  video_filename?: string
  /** ローカル動画が登録済みかどうか（has_video_local 互換）。 */
  has_video_local?: boolean
  video_quality?: string
  camera_angle?: string
  annotator_id?: number
  annotation_status: AnnotationStatus
  annotation_progress: number
  notes?: string
  created_at: string
  updated_at: string
  exception_reason?: ExceptionReason
  // リレーション（フロント側で結合）
  player_a?: Player
  player_b?: Player
  partner_a?: { id: number; name: string; team?: string }
  partner_b?: { id: number; name: string; team?: string }
  // V4: クイックスタート・試合メタデータ
  initial_server?: string
  competition_type?: CompetitionType
  created_via_quick_start?: boolean
  metadata_status?: MetadataStatus
  // Phase B: チーム境界
  owner_team_id?: number | null
  is_public_pool?: boolean
  home_team_id?: number | null
  away_team_id?: number | null
  owner_team_display_id?: string | null
  owner_team_display_name?: string | null
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
  is_skipped?: boolean
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
  land_zone?: LandZone
  is_backhand: boolean
  is_around_head: boolean
  above_net?: boolean
  is_cross: boolean
  timestamp_sec?: number
  epv?: number
  shot_influence?: number
  // N-002: 空間座標拡張
  opponent_contact_x?: number
  opponent_contact_y?: number
  player_contact_x?: number
  player_contact_y?: number
  return_target_x?: number
  return_target_y?: number
}

// アノテーション入力用（IDなし）
export interface StrokeInput {
  stroke_num: number
  player: string
  shot_type: ShotType
  hit_zone?: Zone9
  /** Phase A: 'cv' = 自動推定そのまま / 'manual' = 人間 override */
  hit_zone_source?: 'cv' | 'manual'
  /** Phase A: CV 元推定値 (override 後も保持してデータ品質計測) */
  hit_zone_cv_original?: Zone9 | null
  land_zone?: LandZone
  is_backhand: boolean
  is_around_head: boolean
  above_net?: boolean
  timestamp_sec?: number
  // G2: 返球品質・打点高さ（ストローク確定後オプション入力）
  return_quality?: string   // attack/neutral/defensive/emergency
  contact_height?: string   // overhead/side/underhand/scoop
  // 移動系コンテキスト（4.1 Movement Features）
  contact_zone?: string       // front/mid/rear
  movement_burden?: string    // low/medium/high
  movement_direction?: string // forward/backward/lateral
}

// G3: ウォームアップ観察信頼度
export type WarmupConfidence = 'unknown' | 'tentative' | 'likely' | 'confirmed'

// G3: ウォームアップ観察エントリ
export interface PreMatchObservation {
  match_id: number
  player_id: number
  observation_type: string
  observation_value: string
  confidence_level: WarmupConfidence
  note?: string
  created_by?: string
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

// ─── R-001/R-002: 共有セッション ────────────────────────────────────────────

export interface SharedSession {
  id: number
  match_id: number
  session_code: string
  created_by_role: string
  is_active: boolean
  created_at: string
  ws_connected: number
  coach_urls: string[]
  camera_sender_urls: string[]
  ws_url_template: string
  has_password: boolean
  /** 作成時・再生成時のみ含まれる */
  session_password?: string
}

export type DeviceType = 'iphone' | 'ipad' | 'pc' | 'usb_camera' | 'builtin_camera'
export type ConnectionRole = 'viewer' | 'coach' | 'analyst' | 'camera_candidate' | 'active_camera'
export type ConnectionState = 'idle' | 'receiving_video' | 'sending_video'
export type SourceCapability = 'camera' | 'viewer' | 'none'
export type DeviceApprovalStatus = 'pending' | 'approved' | 'rejected'
export type ViewerPermission = 'allowed' | 'blocked' | 'default'
export type DeviceClass = 'phone' | 'tablet' | 'pc' | 'camera'

export interface SessionParticipant {
  id: number
  session_id: number
  role: string
  device_name: string | null
  device_type: DeviceType | null
  connection_role: ConnectionRole
  source_capability: SourceCapability | null
  video_receive_enabled: boolean
  authenticated_at: string | null
  connection_state: ConnectionState
  joined_at: string
  last_seen_at: string
  is_connected: boolean
  /** migration 0004 */
  device_uid: string | null
  approval_status: DeviceApprovalStatus
  last_heartbeat: string | null
  viewer_permission: ViewerPermission
  device_class: DeviceClass | null
  display_size_class: string
}

/** ライブカメラソース（セッション内ソース管理） */
export interface LiveSource {
  id: number
  session_id: number
  participant_id: number | null
  source_kind: 'iphone_webrtc' | 'ipad_webrtc' | 'usb_camera' | 'builtin_camera' | 'pc_local'
  source_priority: number
  source_resolution: string | null
  source_fps: number | null
  source_status: 'inactive' | 'candidate' | 'active'
  suitability: 'high' | 'usable' | 'fallback'
  created_at: string
  updated_at: string
}

/** ローカルカメラソース（PC 側 getUserMedia で列挙） */
export interface LocalCameraSource {
  deviceId: string
  label: string
  kind: 'videoinput'
  /** USB 接続か内蔵か推定 */
  type: 'usb' | 'builtin' | 'unknown'
}

/** ライブ推論候補 */
export interface LiveInferenceCandidate {
  zone: string | null
  confidence: number
  x_norm: number
  y_norm: number
  available: boolean
  buffering?: boolean
}

// ─── S-003: コメント ──────────────────────────────────────────────────────────

export interface Comment {
  id: number
  match_id: number
  set_id?: number
  rally_id?: number
  stroke_id?: number
  session_id?: number
  author_role: string
  text: string
  is_flagged: boolean
  created_at: string
}

// ─── U-001: イベントブックマーク ─────────────────────────────────────────────

export type BookmarkType = 'manual' | 'coach_request' | 'auto_stat' | 'clip_request'

export interface EventBookmark {
  id: number
  match_id: number
  rally_id?: number
  stroke_id?: number
  bookmark_type: BookmarkType
  video_timestamp_sec?: number
  note?: string
  is_reviewed: boolean
  created_at: string
}

// ─── Q-002/Q-008: ネットワーク診断 ──────────────────────────────────────────

export interface NetworkDiagnostics {
  environment: 'open' | 'corporate_proxy' | 'vpn' | 'filtered' | 'captive_portal' | 'unknown'
  capabilities: {
    tcp_443: { ok: boolean; error?: string }
    tcp_80: { ok: boolean; error?: string }
    localhost_bridge: { ok: boolean; error?: string }
    proxy_detected: boolean
    proxy_env_vars: Record<string, string>
  }
  lan: {
    lan_ips: string[]
    lan_mode_enabled: boolean
    api_port: number
    accessible: boolean
  }
  platform: { os: string; version: string; hostname: string }
  transport_ladder: string[]
  probe_duration_ms: number
}
