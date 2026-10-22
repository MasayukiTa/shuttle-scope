// POST /api/v1/expert/labels の本文。
// backend の LabelPayload（routers/expert.py）は extra=forbid で、キーはここに並べたものだけ。
// フレーム範囲（frame_index / clip_*_frame）は stroke の timestamp_sec から再計算できるため送らない。
// 「スキップ」は保存しない（呼び出し側で次のクリップへ進むだけ）。ラベル列に 'skipped' のような
// 値を入れると、書き出しと集計に判定でも欠測でもない値が混ざる。

export type PostureCollapse = 'none' | 'minor' | 'major'
export type WeightDistribution = 'left' | 'right' | 'center' | 'floating'
export type ShotTiming = 'early' | 'optimal' | 'late'
export type LabelConfidence = 1 | 2 | 3

export interface ExpertLabelFormValues {
  posture_collapse: PostureCollapse
  weight_distribution: WeightDistribution
  shot_timing: ShotTiming
  confidence: LabelConfidence
  comment: string
}

export interface ExpertLabelRequest extends ExpertLabelFormValues {
  match_id: number
  stroke_id: number
  annotator_role: 'coach' | 'analyst'
}

export function buildExpertLabelRequest(
  matchId: string | number,
  strokeId: number,
  annotatorRole: 'coach' | 'analyst',
  form: ExpertLabelFormValues,
): ExpertLabelRequest {
  return {
    match_id: Number(matchId),
    stroke_id: strokeId,
    annotator_role: annotatorRole,
    posture_collapse: form.posture_collapse,
    weight_distribution: form.weight_distribution,
    shot_timing: form.shot_timing,
    confidence: form.confidence,
    comment: form.comment,
  }
}
