/**
 * Regression (T010b): the badminton period is called "Game" / 「ゲーム」 in the
 * inline i18n `defaultValue` fallbacks embedded in component source, not just in
 * the ja/en dictionaries.
 *
 * Why this is separate from gameWordingUnified.t010:
 *   T010 scans ONLY the string VALUES in ja.json / en.json. Several screens call
 *   t('key', { defaultValue: 'Set {{n}}' }) with the English fallback written
 *   inline in the .tsx source. Those literals are what renders if the key is ever
 *   missing, and they are NOT covered by the JSON scan — so a "Set N" period
 *   fallback could sit in the source while every dictionary value already said
 *   "Game". This test locks the inline fallbacks on the analysis / annotator
 *   screens so the period wording cannot silently regress there.
 *
 * Scope: `defaultValue:` string literals in the component sources below. Internal
 * keys, variable names (e.g. GameSet, setMidGameShown) and comments are not user
 * facing and are not checked. "set" in unrelated meanings (reset, setup, the verb
 * "set") is not matched because we only forbid the sport-period noun patterns.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const srcRoot = resolve(here, '..', '..') // src/

// Files that embed inline i18n defaultValue fallbacks for the period label.
const FILES = [
  'components/analysis/RallyClipNavigator.tsx',
  'pages/AnnotatorPage.tsx',
]

// Sport-period "Set" patterns that must not appear in any defaultValue literal.
const PERIOD_PATTERNS = [
  /\bSet\s+\{\{/, // "Set {{n}}", "Set {{set}}", "Set {{from}}"
  /\bSet\s+\d/, // "Set 1"
]

// Match a defaultValue literal: defaultValue: 'single' or "double" quotes.
const DEFAULT_VALUE_RE = /defaultValue:\s*(['"])((?:\\.|(?!\1).)*)\1/g

describe('要望7 「セット」→「ゲーム」 inline defaultValue fallbacks (T010b)', () => {
  for (const rel of FILES) {
    it(`${rel}: no defaultValue fallback uses "Set" as the sport period`, () => {
      const text = readFileSync(resolve(srcRoot, rel), 'utf-8')
      const offenders: string[] = []
      for (const m of text.matchAll(DEFAULT_VALUE_RE)) {
        const literal = m[2]
        if (PERIOD_PATTERNS.some((re) => re.test(literal))) {
          offenders.push(JSON.stringify(literal))
        }
      }
      expect(offenders).toEqual([])
    })
  }

  it('found and checked at least one defaultValue literal per file (guard not vacuous)', () => {
    for (const rel of FILES) {
      const text = readFileSync(resolve(srcRoot, rel), 'utf-8')
      const count = [...text.matchAll(DEFAULT_VALUE_RE)].length
      expect(count).toBeGreaterThan(0)
    }
  })
})
