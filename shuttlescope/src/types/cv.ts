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
  /**
   * 成果物の来歴。バックエンドは前から記録していたが **画面が一度も読んで
   * いなかった**ので、候補が空でも理由が分からなかった。
   *
   * - `calibrated`: コートキャリブレーション済みか。無いと着地ゾーン候補は
   *   一件も出ない（CV は画像座標から Zone9 を名乗らない）
   * - `player_a_start_side_known`: 開始サイドが入っているか。無いと CV の
   *   `player_a`（画面の上側）を人に翻訳できず、打者候補が要確認に落ちる
   * - `fps_known`: fps を推定できたか。false なら秒→フレーム換算がずれうる
   * - `alignment_failed`: アライメント計算が失敗したときの理由
   */
  calibrated?: boolean
  player_a_start_side_known?: boolean
  fps_known?: boolean
  alignment_failed?: string | null
}

export interface ReviewQueueItem {
  rally_id: number
  rally_num: number
  set_id: number
  review_status: string
  cv_reason_codes: string[]
}
