/**
 * mobileAnnotateShotSuggest - Pass3 add-stroke "next shot_type candidate pre-surface" utility (v2).
 *
 * Purpose:
 *   When adding a stroke in Pass3, from the previous stroke's shot_type IN THE SAME RALLY,
 *   surface the top-3 next shot_type candidates as the FIRST chips in the chip row.
 *   One tap confirms; a different pick falls back to the full 18-chip grid.
 *
 * Design contract (important):
 *   - This is candidate *surfacing* (reorder + show), NOT auto-commit. Unlike land_zone (v1),
 *     it NEVER pre-SELECTs a chip: a wrongly auto-selected shot_type is harder to notice than a
 *     zone, so we only place "candidate"-looking chips at the front; the user still taps to confirm.
 *   - When data is insufficient, show NO candidate. If the raw transition support from prev shot
 *     is below the threshold (reuse markov bootstrap >=10 convention), return empty -> the UI shows
 *     the full 18 chips as before. Laplace alpha=1 makes the row defined even at n=0, so a support
 *     gate is mandatory or the chips are pure noise.
 *   - Every surfaced candidate carries a confidence tier (project rule: always show uncertainty).
 *
 * Candidate source:
 *   Reproduce the existing markov transition matrix (backend/analysis/markov.py
 *   build_transition_matrix, 18x18, row-normalized, Laplace alpha=1.0) on the client.
 *   Per design E-b401a5d18979 "return the full transition row once per match" variant: build the
 *   counts from the already-fetched strokes instead of a per-stroke round-trip.
 */

/**
 * The exact 18 shot_type vocabulary the mobile chips already use (canonical ShotType values).
 * COMMON 8 + OTHER 9 + other = 18. Same set as markov.py SHOT_KEYS (no vocabulary mapping).
 * Kept in sync with Pass3ShotDetail.tsx COMMON_SHOT_KEYS / OTHER_SHOT_KEYS / 'other'.
 */
export const SHOT_KEYS = [
  // COMMON 8 (fixed chips)
  'smash', 'clear', 'drop', 'net_shot', 'push_rush', 'drive', 'lob', 'cross_net',
  // OTHER 9 (folded)
  'short_service', 'long_service', 'defensive', 'slice', 'around_head',
  'cant_reach', 'flick', 'half_smash', 'block',
  // other (detail later)
  'other',
] as const

export type ShotKey = typeof SHOT_KEYS[number]

const SHOT_KEY_SET: ReadonlySet<string> = new Set<string>(SHOT_KEYS)

/** Type guard: is value one of the canonical 18 shot_type keys. */
export function isShotKey(value: unknown): value is ShotKey {
  return typeof value === 'string' && SHOT_KEY_SET.has(value)
}

/**
 * Confidence tier (reuses the decision_mode 3-level trust, same vocab as land_zone CV)
 * so the UI badge is shared.
 *   - auto_filled     : most reliable (high support + high share)
 *   - suggested       : medium
 *   - review_required : needs a human eye (low share)
 */
export type SuggestTier = 'auto_filled' | 'suggested' | 'review_required'

export interface ShotSuggestion {
  /** Candidate shot_type (one of the canonical 18). */
  shot_type: ShotKey
  /** Normalized probability of the prev row (after Laplace alpha=1). 0..1. */
  confidence_score: number
  /** Confidence tier for the UI badge. */
  decision_mode: SuggestTier
}

/** One stroke (only the needed fields). */
export interface SuggestStroke {
  stroke_num?: number | null
  shot_type?: string | null
}

/** One rally (only the needed fields). */
export interface SuggestRally {
  strokes?: SuggestStroke[] | null
}

export interface BuildShotSuggestOptions {
  /** If the raw transition support from prev is below this, emit no candidate. Default 10 (markov >=10). */
  minSupport?: number
  /** How many top candidates to return. Default 3. */
  topN?: number
}

const DEFAULT_MIN_SUPPORT = 10
const DEFAULT_TOP_N = 3

/**
 * 18x18 raw transition counts (prev shot_type -> next shot_type -> count).
 * Corresponds to the pre-Laplace part of markov.py build_transition_matrix.
 */
export type TransitionCounts = ReadonlyMap<ShotKey, ReadonlyMap<ShotKey, number>>

/**
 * Build 18x18 raw transition counts from already-fetched rallies/strokes.
 *
 * - A count is a (prev.shot_type -> next.shot_type) pair of CONSECUTIVE strokes within ONE rally.
 * - Never pair across rally boundaries (a cross-rally sequence is not a transition).
 * - Order by stroke_num ascending first; non-integer stroke_num is dropped.
 * - shot_type outside the canonical 18 (serve / __final_pending / unclassified) is NOT a transition
 *   endpoint (markov.py truncate_at_stray_service analogue: break the chain at out-of-vocab shots).
 */
export function buildTransitionCounts(
  rallies: ReadonlyArray<SuggestRally | null | undefined> | null | undefined,
): TransitionCounts {
  const counts = new Map<ShotKey, Map<ShotKey, number>>()
  if (!Array.isArray(rallies)) return counts
  for (const rally of rallies) {
    if (!rally || !Array.isArray(rally.strokes)) continue
    const ordered = rally.strokes
      .filter((s: SuggestStroke): s is SuggestStroke => !!s && typeof s.stroke_num === 'number' && Number.isInteger(s.stroke_num))
      .slice()
      .sort((a: SuggestStroke, b: SuggestStroke) => (a.stroke_num as number) - (b.stroke_num as number))
    for (let i = 0; i + 1 < ordered.length; i++) {
      const prev = ordered[i].shot_type
      const next = ordered[i + 1].shot_type
      if (!isShotKey(prev) || !isShotKey(next)) continue
      let row = counts.get(prev)
      if (!row) { row = new Map<ShotKey, number>(); counts.set(prev, row) }
      row.set(next, (row.get(next) ?? 0) + 1)
    }
  }
  return counts
}

/** Raw support of the prev row (= sum of all transitions out of prev). */
export function supportOf(counts: TransitionCounts, prevShot: string): number {
  if (!isShotKey(prevShot)) return 0
  const row = counts.get(prevShot)
  if (!row) return 0
  let sum = 0
  for (const c of row.values()) sum += c
  return sum
}

/**
 * Map a share (post-Laplace normalized probability) to a confidence tier.
 * Markov smears toward uniform on small samples, so low-share picks are always tentative.
 */
export function tierOf(prob: number): SuggestTier {
  if (prob >= 0.5) return 'auto_filled'
  if (prob >= 0.25) return 'suggested'
  return 'review_required'
}

/**
 * Return the top-N next shot_type candidates from the prev shot's row.
 *
 * - If the raw support from prev is below minSupport, return [] (insufficient data -> no candidate).
 * - Laplace alpha=1 smoothing over all 18 keys, then normalize, then sort by share desc.
 * - Ties are broken deterministically by shot_type dictionary order (SHOT_KEYS order).
 * - If prev is out of vocab, return [] (do not suggest after serve / __final_pending).
 */
export function pickNextShotSuggestions(
  counts: TransitionCounts,
  prevShot: string | null | undefined,
  options: BuildShotSuggestOptions = {},
): ShotSuggestion[] {
  const minSupport = options.minSupport ?? DEFAULT_MIN_SUPPORT
  const topN = options.topN ?? DEFAULT_TOP_N
  if (!isShotKey(prevShot)) return []
  const support = supportOf(counts, prevShot)
  if (support < minSupport) return []
  const row = counts.get(prevShot) ?? new Map<ShotKey, number>()
  const alpha = 1
  const denom = support + alpha * SHOT_KEYS.length
  const ranked = SHOT_KEYS.map((key, idx) => {
    const c = row.get(key) ?? 0
    const prob = (c + alpha) / denom
    return { key, idx, prob }
  })
  ranked.sort((a, b) => (b.prob - a.prob) || (a.idx - b.idx))
  return ranked.slice(0, topN).map((r) => ({
    shot_type: r.key,
    confidence_score: r.prob,
    decision_mode: tierOf(r.prob),
  }))
}

/**
 * Build a prev shot_type -> top candidates map from already-fetched rallies in one shot.
 * Pass3 just looks up this map by the previous shot_type.
 * A prev whose candidates are empty (support below threshold) is not added -> UI unchanged there.
 */
export function buildShotTypeSuggestions(
  rallies: ReadonlyArray<SuggestRally | null | undefined> | null | undefined,
  options: BuildShotSuggestOptions = {},
): Map<string, ShotSuggestion[]> {
  const out = new Map<string, ShotSuggestion[]>()
  const counts = buildTransitionCounts(rallies)
  for (const prev of SHOT_KEYS) {
    const sug = pickNextShotSuggestions(counts, prev, options)
    if (sug.length > 0) out.set(prev, sug)
  }
  return out
}

/**
 * Whether to surface next shot_type candidates for this role.
 * Not shown on the player screen; analyst / coach only (operator roles, like cv_candidates).
 * Unknown role (null/undefined) falls to the no-assist side (safer than a wrong surface).
 */
export function canSuggestShotType(role: string | null | undefined): boolean {
  return role === 'analyst' || role === 'coach'
}
