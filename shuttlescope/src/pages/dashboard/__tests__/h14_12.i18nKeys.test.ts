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

// h14_12: error-state messages added for audit items #594, #597, #599.
// Each user-facing key must exist and be a non-empty string in BOTH locales
// so the static t() key check and the UI error states never fall back to a
// raw key or an empty default.
const REQUIRED_KEYS = [
  'annotator.identify_save_failed',
  'in_match_panel.save_failed',
  'auto.DashboardLivePage.set_detail_error',
]

describe('h14_12 error-state i18n keys', () => {
  for (const key of REQUIRED_KEYS) {
    it(`ja.json defines ${key}`, () => {
      const v = lookup(ja as Dict, key)
      expect(typeof v).toBe('string')
      expect((v as string).length).toBeGreaterThan(0)
    })
    it(`en.json defines ${key}`, () => {
      const v = lookup(en as Dict, key)
      expect(typeof v).toBe('string')
      expect((v as string).length).toBeGreaterThan(0)
    })
  }
})
