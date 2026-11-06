import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

import en from '../../../i18n/en.json'
import ja from '../../../i18n/ja.json'

type Dict = { [k: string]: unknown }

function lookup(obj: Dict, path: string): unknown {
  return path.split('.').reduce<unknown>((acc, key) => {
    if (acc && typeof acc === 'object') return (acc as Dict)[key]
    return undefined
  }, obj)
}

// Audit item 143: the DR-OPE CI label did not say which quantity the interval
// covers. ci_low/ci_high are the CI of value_target (the target-policy win
// rate, see backend/analysis/dr_ope_engine.py), NOT of the uplift, but the card
// printed them with a signed percent (e.g. "95% CI: +51.7% ~ +55.4%"), which
// read like an uplift CI next to the uplift headline. The fix labels the band as
// the target win-rate CI and renders the bounds as unsigned percents (pct1), so
// the uplift (signed, in the headline) and the win-rate CI stay distinct.

const CI_KEY = 'auto.PolicyEvalCard.ci_range'

describe('item 143: DR-OPE CI label disambiguates target win-rate from uplift', () => {
  it('ja ci_range names the target win-rate and keeps the placeholders', () => {
    const v = lookup(ja as Dict, CI_KEY)
    expect(typeof v).toBe('string')
    const s = v as string
    expect(s).toContain('目標勝率')
    expect(s).toContain('{{low}}')
    expect(s).toContain('{{high}}')
    expect(s).toContain('{{width}}')
  })

  it('en ci_range names the target win-rate and keeps the placeholders', () => {
    const v = lookup(en as Dict, CI_KEY)
    expect(typeof v).toBe('string')
    const s = v as string
    expect(s.toLowerCase()).toContain('target win-rate')
    expect(s).toContain('{{low}}')
    expect(s).toContain('{{high}}')
    expect(s).toContain('{{width}}')
  })

  it('the card renders the CI bounds as unsigned percents (pct1), not signedPct', () => {
    const here = dirname(fileURLToPath(import.meta.url))
    const src = readFileSync(resolve(here, '../PolicyEvalCard.tsx'), 'utf8')
    const call = src.slice(src.indexOf("t('auto.PolicyEvalCard.ci_range'"))
    const block = call.slice(0, call.indexOf('})'))
    expect(block).toContain('low: pct1(row.ci_low)')
    expect(block).toContain('high: pct1(row.ci_high)')
    expect(block).not.toContain('signedPct(row.ci_low)')
    expect(block).not.toContain('signedPct(row.ci_high)')
  })
})
