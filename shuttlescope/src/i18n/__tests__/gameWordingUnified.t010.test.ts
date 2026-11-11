/**
 * Regression: the badminton period is called 「ゲーム」 / "Game" on every screen.
 *
 * A customer asked to replace the sport-period wording 「セット」 with 「ゲーム」
 * across the whole product (record, list, registration AND the analysis /
 * settings / live screens). This test locks that in so the wording cannot
 * silently regress on any screen.
 *
 * Scope: user-facing STRING VALUES in the ja / en dictionaries only. Internal
 * keys, code comments and variable names are not checked (they are never shown
 * to a user). The word 「セット」 / "set" also appears in unrelated meanings
 * (リセット = reset, セットアップ = setup, "prediction set", the verb "set",
 * "set up"); those are excluded so only the sport-period meaning is enforced.
 */
import { describe, it, expect } from 'vitest'
import ja from '@/i18n/ja.json'
import en from '@/i18n/en.json'

// Walk a nested dictionary and yield [dottedKeyPath, stringValue] for every leaf string.
function* leaves(obj: unknown, path: string[] = []): Generator<[string, string]> {
  if (typeof obj === 'string') {
    yield [path.join('.'), obj]
    return
  }
  if (obj && typeof obj === 'object') {
    for (const [k, v] of Object.entries(obj as Record<string, unknown>)) {
      yield* leaves(v, [...path, k])
    }
  }
}

// Japanese compounds that contain 「セット」 but are NOT the sport period.
const JA_ALLOWED = [
  'リセット', // reset
  'セットアップ', // setup
  'データセット', // dataset
  'サブセット', // subset
  'プリセット', // preset
  '校正セット', // calibration set
  'テストセット', // test set
  '予測セット', // prediction set (conformal)
  '要素セット', // element set (conformal)
  '候補セット', // candidate set
  '色のセット', // set of colors
]

function stripJaAllowed(s: string): string {
  let out = s
  for (const w of JA_ALLOWED) out = out.split(w).join('')
  return out
}

// English sport-period patterns that must no longer appear in any user-facing value.
// ("set" also means the verb "set" / "set up" and the statistics term "prediction set",
//  so we only forbid the specific noun patterns the period labels used.)
const EN_PERIOD_PATTERNS = [
  /\bset\s+\d/i, // "Set 1"
  /\bset\s*\{\{/i, // "Set {{n}}"
  /\bnext\s+set\b/i,
  /\bprevious\s+set\b/i,
  /\bper\s+set\b/i,
  /\bset-by-set\b/i,
  /\bbest[- ]of[- ]\d+\s+sets?\b/i,
]

describe('要望7 「セット」→「ゲーム」 is unified on every screen (T010)', () => {
  it('ja: no user-facing value uses 「セット」 as the sport period', () => {
    const offenders: string[] = []
    for (const [key, val] of leaves(ja)) {
      if (stripJaAllowed(val).includes('セット')) {
        offenders.push(`${key} = ${JSON.stringify(val)}`)
      }
    }
    expect(offenders).toEqual([])
  })

  it('en: no user-facing value uses "set" as the sport period', () => {
    const offenders: string[] = []
    for (const [key, val] of leaves(en)) {
      if (EN_PERIOD_PATTERNS.some((re) => re.test(val))) {
        offenders.push(`${key} = ${JSON.stringify(val)}`)
      }
    }
    expect(offenders).toEqual([])
  })

  // Lock the specific period-label keys that each screen renders.
  it('ja: period labels across record / analysis / live screens say 「ゲーム」', () => {
    const d = ja as any
    expect(d.annotator.set).toBe('ゲーム')
    expect(d.analysis.interval_report.set).toBe('ゲーム')
    expect(d.analysis.score_progression.set_selector).toBe('ゲーム')
    // analysis screens still mention 「ゲーム」 and no longer the old period wording.
    expect(JSON.stringify(d.analysis)).toContain('ゲーム')
    expect(JSON.stringify(d.analysis)).not.toContain('セット別')
    expect(JSON.stringify(d.analysis)).not.toContain('第1セット')
  })

  it('en: period labels across screens say "Game"', () => {
    const d = en as any
    expect(d.annotator.set).toBe('Game')
    expect(JSON.stringify(d.analysis)).not.toMatch(/\bSet\s+\d/)
  })
})
