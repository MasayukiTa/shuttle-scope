/**
 * CV補助アノテーション候補の型定義
 *
 * decision_mode:
 *   auto_filled      — 高確信度: 自動入力済み。オペレーターは確認のみ
 *   suggested        — 中確信度: 候補を提示。ワンタップで確定
 *   review_required  — 低確信度: 入力なし、要確認フラグ
 *
 * source:
 *   tracknet   — TrackNet シャトル軌跡のみ
 *   yolo       — YOLO 検出のみ
 *   alignment  — YOLO + TrackNet アライメント結果
 *   fusion     — 複数ソースの融合
 */

export type CVDecisionMode = 'auto_filled' | 'suggested' | 'review_required'
export type CVSource = 'tracknet' | 'yolo' | 'alignment' | 'fusion'
export type CVFrontBackRole = 'front' | 'back' | 'unclear'
export type CVDominantRole = 'front' | 'back' | 'mixed'

export interface CVFieldResult {
  value: string
  confidence_score: number
  source: CVSource
  decision_mode: CVDecisionMode
  reason_codes: string[]
}

export interface CVFrontBackRoleResult {
  player_a: CVFrontBackRole
  player_b: CVFrontBackRole
  confidence: number
}

export interface CVRallyFrontBackSignal {
  player_a_dominant: CVDominantRole
  player_b_dominant: CVDominantRole
  stability: number
}

export interface StrokeCVCandidate {
  stroke_id: number | null
  stroke_num: number
  timestamp_sec: number | null
  land_zone: CVFieldResult | null
  hitter: CVFieldResult | null
  front_back_role: CVFrontBackRoleResult | null
}

export interface CVConfidenceSummary {
  land_zone_fill_rate: number
  hitter_fill_rate: number
  avg_confidence: number
}

export interface RallyCVCandidate {
  rally_id: number
  cv_assist_available: boolean
  cv_confidence_summary: CVConfidenceSummary
  front_back_role_signal: CVRallyFrontBackSignal | null
  review_reason_codes: string[]
  strokes: StrokeCVCandidate[]
}

export interface CVCandidatesData {
  match_id: number
  built_at: string
  rallies: Record<string, RallyCVCandidate>
}

export interface ReviewQueueItem {
  rally_id: number
  rally_num: number
  set_id: number
  review_status: string
  cv_reason_codes: string[]
}
