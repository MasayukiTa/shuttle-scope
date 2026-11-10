import { describe, it, expect } from 'vitest'
import {
  SHOT_KEYS,
  isShotKey,
  tierOf,
  supportOf,
  buildTransitionCounts,
  pickNextShotSuggestions,
  buildShotTypeSuggestions,
  canSuggestShotType,
  type SuggestRally,
} from '../mobileAnnotateShotSuggest'

// Helper: a rally from a list of shot_type strings, stroke_num = index+1.
function rally(shots: Array<string | null>): SuggestRally {
  return { strokes: shots.map((s, i) => ({ stroke_num: i + 1, shot_type: s })) }
}

// Build N rallies that each contribute one prev->next pair "from"->"to".
function pairRallies(from: string, to: string, n: number): SuggestRally[] {
  return Array.from({ length: n }, () => rally([from, to]))
}

describe('SHOT_KEYS vocabulary', () => {
  it('has exactly 18 canonical shot types incl. other', () => {
    expect(SHOT_KEYS.length).toBe(18)
    expect(SHOT_KEYS).toContain('other')
    expect(new Set(SHOT_KEYS).size).toBe(18) // no duplicates
  })
  it('isShotKey accepts vocab and rejects out-of-vocab', () => {
    expect(isShotKey('smash')).toBe(true)
    expect(isShotKey('serve')).toBe(false)
    expect(isShotKey('__final_pending')).toBe(false)
    expect(isShotKey('SMASH')).toBe(false)
    expect(isShotKey(null)).toBe(false)
    expect(isShotKey(42)).toBe(false)
  })
})

describe('tierOf', () => {
  it('maps share to tier', () => {
    expect(tierOf(0.6)).toBe('auto_filled')
    expect(tierOf(0.5)).toBe('auto_filled')
    expect(tierOf(0.3)).toBe('suggested')
    expect(tierOf(0.25)).toBe('suggested')
    expect(tierOf(0.1)).toBe('review_required')
  })
})

describe('buildTransitionCounts', () => {
  it('counts consecutive in-vocab pairs within a rally', () => {
    const counts = buildTransitionCounts([rally(['clear', 'drop', 'net_shot'])])
    expect(counts.get('clear')?.get('drop')).toBe(1)
    expect(counts.get('drop')?.get('net_shot')).toBe(1)
  })
  it('does not pair across rally boundaries', () => {
    const counts = buildTransitionCounts([rally(['clear']), rally(['drop'])])
    expect(counts.get('clear')).toBeUndefined()
  })
  it('breaks the chain at out-of-vocab shots (serve / __final_pending)', () => {
    // serve -> clear should NOT count (serve out of vocab); clear -> __final_pending neither.
    const counts = buildTransitionCounts([rally(['serve', 'clear', '__final_pending'])])
    expect(counts.get('serve' as never)).toBeUndefined()
    expect(counts.get('clear')?.get('__final_pending' as never)).toBeUndefined()
    // clear has no valid next here -> row absent or empty
    expect(supportOf(counts, 'clear')).toBe(0)
  })
  it('ignores non-integer stroke_num and orders by stroke_num', () => {
    const r: SuggestRally = { strokes: [
      { stroke_num: 2, shot_type: 'drop' },
      { stroke_num: 1, shot_type: 'clear' },
      { stroke_num: 1.5, shot_type: 'smash' }, // dropped
    ] }
    const counts = buildTransitionCounts([r])
    expect(counts.get('clear')?.get('drop')).toBe(1)
    expect(counts.get('clear')?.get('smash' as never)).toBeUndefined()
  })
  it('tolerates null / empty input', () => {
    expect(buildTransitionCounts(null).size).toBe(0)
    expect(buildTransitionCounts([null, undefined]).size).toBe(0)
    expect(buildTransitionCounts([{ strokes: null }]).size).toBe(0)
  })
})

describe('pickNextShotSuggestions - support gate', () => {
  it('returns [] when support below threshold (default 10)', () => {
    const counts = buildTransitionCounts(pairRallies('clear', 'drop', 9))
    expect(supportOf(counts, 'clear')).toBe(9)
    expect(pickNextShotSuggestions(counts, 'clear')).toEqual([])
  })
  it('returns candidates when support meets threshold', () => {
    const counts = buildTransitionCounts(pairRallies('clear', 'drop', 10))
    expect(supportOf(counts, 'clear')).toBe(10)
    const sug = pickNextShotSuggestions(counts, 'clear')
    expect(sug.length).toBe(3)
    expect(sug[0].shot_type).toBe('drop')
  })
  it('honours a custom minSupport', () => {
    const counts = buildTransitionCounts(pairRallies('clear', 'drop', 5))
    expect(pickNextShotSuggestions(counts, 'clear', { minSupport: 5 }).length).toBe(3)
    expect(pickNextShotSuggestions(counts, 'clear', { minSupport: 6 })).toEqual([])
  })
  it('returns [] for out-of-vocab or missing prev', () => {
    const counts = buildTransitionCounts(pairRallies('clear', 'drop', 20))
    expect(pickNextShotSuggestions(counts, 'serve')).toEqual([])
    expect(pickNextShotSuggestions(counts, null)).toEqual([])
    expect(pickNextShotSuggestions(counts, undefined)).toEqual([])
  })
})

describe('pickNextShotSuggestions - ranking', () => {
  it('returns at most top-3 ordered by share desc', () => {
    // clear -> drop x10, clear -> smash x6, clear -> net_shot x4 (support 20)
    const counts = buildTransitionCounts([
      ...pairRallies('clear', 'drop', 10),
      ...pairRallies('clear', 'smash', 6),
      ...pairRallies('clear', 'net_shot', 4),
    ])
    expect(supportOf(counts, 'clear')).toBe(20)
    const sug = pickNextShotSuggestions(counts, 'clear')
    expect(sug.map((s) => s.shot_type)).toEqual(['drop', 'smash', 'net_shot'])
    // confidence is the post-Laplace normalized prob; strictly descending here
    expect(sug[0].confidence_score).toBeGreaterThan(sug[1].confidence_score)
    expect(sug[1].confidence_score).toBeGreaterThan(sug[2].confidence_score)
    // each carries a tier (uncertainty shown)
    sug.forEach((s) => expect(['auto_filled', 'suggested', 'review_required']).toContain(s.decision_mode))
  })
  it('breaks ties deterministically by SHOT_KEYS order', () => {
    // clear -> smash x5, clear -> clear x5, clear -> drop x5 (all tied at 5; support 15)
    const counts = buildTransitionCounts([
      ...pairRallies('clear', 'smash', 5),
      ...pairRallies('clear', 'clear', 5),
      ...pairRallies('clear', 'drop', 5),
    ])
    expect(supportOf(counts, 'clear')).toBe(15)
    const sug = pickNextShotSuggestions(counts, 'clear')
    // SHOT_KEYS order: smash(0), clear(1), drop(2) -> that exact order on ties
    expect(sug.map((s) => s.shot_type)).toEqual(['smash', 'clear', 'drop'])
  })
  it('respects a custom topN', () => {
    const counts = buildTransitionCounts([
      ...pairRallies('clear', 'drop', 10),
      ...pairRallies('clear', 'smash', 6),
    ])
    expect(pickNextShotSuggestions(counts, 'clear', { topN: 1 }).length).toBe(1)
  })
})

describe('buildShotTypeSuggestions', () => {
  it('only includes prev keys whose support meets the threshold', () => {
    const map = buildShotTypeSuggestions([
      ...pairRallies('clear', 'drop', 12), // enough
      ...pairRallies('smash', 'net_shot', 3), // too few
    ])
    expect(map.has('clear')).toBe(true)
    expect(map.has('smash')).toBe(false)
    expect(map.get('clear')?.[0].shot_type).toBe('drop')
  })
  it('is empty on insufficient / empty data', () => {
    expect(buildShotTypeSuggestions(null).size).toBe(0)
    expect(buildShotTypeSuggestions([]).size).toBe(0)
  })
})

describe('canSuggestShotType - role gate', () => {
  it('allows analyst and coach only', () => {
    expect(canSuggestShotType('analyst')).toBe(true)
    expect(canSuggestShotType('coach')).toBe(true)
  })
  it('denies player and other roles and unknown', () => {
    expect(canSuggestShotType('player')).toBe(false)
    expect(canSuggestShotType('admin')).toBe(false)
    expect(canSuggestShotType('demo')).toBe(false)
    expect(canSuggestShotType('llm')).toBe(false)
    expect(canSuggestShotType(null)).toBe(false)
    expect(canSuggestShotType(undefined)).toBe(false)
  })
})
