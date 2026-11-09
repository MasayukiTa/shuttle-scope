/**
 * mobileAnnotateCvSuggest — Pass3 着地ゾーン入力の「CV 候補の先出し」専用ユーティリティ。
 *
 * 目的:
 *   記録者が Pass3 で各ストロークの着地ゾーン (land_zone) をタップ入力する際、
 *   既に生成済みの CV 候補 (cv_candidates アーティファクト) の land_zone を
 *   AnnotateOverlay の initialZone として「先に選択済み」で見せる。記録者は
 *   そのまま確定すれば 1 タップ、違えば普通にタップし直すだけで済む。
 *
 * 設計上の約束 (重要):
 *   - これは *候補の先出し* であって自動確定ではない。確定は従来どおり記録者の
 *     onCommit (= enqueue) でのみ起きる。この関数は「どのゾーンを初期選択にするか」
 *     を決めるだけで、ネットワーク送信も保存も一切しない。
 *   - 自信の無い候補は初期選択にしない。decision_mode === 'review_required' の候補と、
 *     Zone9 語彙 (BL..NR) 以外の値は捨てる。半分の確率で逆のゾーンを「既定」に
 *     置くと、記録者が気付かず確定してデータを汚すため。
 *   - land_zone 候補はキャリブレーション済みかつ homography を通った試合でしか
 *     生成されない (backend: candidate_builder)。未校正・モデル無しの試合では
 *     cv_candidates が空 → この関数は空 Map を返し、UI は従来どおり初期選択なしで動く。
 *
 * CV 候補の由来:
 *   GET /cv-candidates/{match_id} の rallies[rally_id].strokes[].land_zone。
 *   land_zone は { value, confidence_score, decision_mode, reason_codes } の形。
 *   value は backend/config.ZONES_9 と同じ 9 値 (BL/BC/BR/ML/MC/MR/NL/NC/NR)。
 */
import type { ZoneCode } from '@/components/mobileAnnotate/AnnotateOverlay'

/** AnnotateOverlay.ZoneCode と同一の 9 ゾーン語彙。文字列候補の検証に使う。 */
const ZONE9: ReadonlySet<string> = new Set<ZoneCode>([
  'BL', 'BC', 'BR',
  'ML', 'MC', 'MR',
  'NL', 'NC', 'NR',
])

/** cv_candidates の land_zone 候補 (必要な項目のみ)。 */
export interface CvLandZone {
  value?: string | null
  confidence_score?: number | null
  decision_mode?: string | null
}

/** cv_candidates の stroke 候補 (必要な項目のみ)。 */
export interface CvSuggestStroke {
  stroke_num?: number | null
  land_zone?: CvLandZone | null
}

/** cv_candidates の rally 候補 (必要な項目のみ)。 */
export interface CvSuggestRally {
  strokes?: CvSuggestStroke[] | null
}

export interface BuildLandZoneSuggestionsOptions {
  /**
   * この信頼度未満の候補は先出ししない。既定 0 (= 信頼度では切らない)。
   * decision_mode === 'review_required' は信頼度に関係なく常に除外する。
   */
  minConfidence?: number
}

/**
 * 1 つのゾーン文字列が Zone9 語彙かを判定し、ZoneCode へ絞り込む (type guard)。
 */
export function isZoneCode(value: unknown): value is ZoneCode {
  return typeof value === 'string' && ZONE9.has(value)
}

/**
 * 単一の land_zone 候補を「先出ししてよいか」判定し、採用するなら ZoneCode を返す。
 * 採用しない (自信不足・語彙外・欠落) 場合は null。
 */
export function pickLandZoneSuggestion(
  land: CvLandZone | null | undefined,
  options: BuildLandZoneSuggestionsOptions = {},
): ZoneCode | null {
  if (!land) return null
  // review_required は「人が見ないと危ない」と CV 自身が言っている候補。初期選択にしない。
  if (land.decision_mode === 'review_required') return null
  if (!isZoneCode(land.value)) return null
  const minConfidence = options.minConfidence ?? 0
  if (minConfidence > 0) {
    const conf = land.confidence_score
    if (typeof conf !== 'number' || Number.isNaN(conf) || conf < minConfidence) {
      return null
    }
  }
  return land.value
}

/**
 * 1 ラリー分の CV 候補から `stroke_num -> ZoneCode` の先出しマップを作る。
 *
 * - stroke_num が整数でない候補は無視する (対応付けできないため)。
 * - 同じ stroke_num が重複する場合は最初に出たものを優先する (CV 側は通常一意)。
 * - 採用されない候補 (review_required / 語彙外 / 低信頼) はマップに入れない
 *   → UI 側は「候補のある stroke だけ」初期選択が付く。
 */
export function buildLandZoneSuggestions(
  rally: CvSuggestRally | null | undefined,
  options: BuildLandZoneSuggestionsOptions = {},
): Map<number, ZoneCode> {
  const out = new Map<number, ZoneCode>()
  if (!rally || !Array.isArray(rally.strokes)) return out
  for (const s of rally.strokes) {
    if (!s) continue
    const n = s.stroke_num
    if (typeof n !== 'number' || !Number.isInteger(n)) continue
    if (out.has(n)) continue
    const zone = pickLandZoneSuggestion(s.land_zone, options)
    if (zone) out.set(n, zone)
  }
  return out
}
