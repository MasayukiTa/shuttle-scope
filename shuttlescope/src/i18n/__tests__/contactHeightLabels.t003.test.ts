import { describe, it, expect } from 'vitest'
import ja from '@/i18n/ja.json'
import en from '@/i18n/en.json'

// F-T003-06: customer request #8 asked that contact-height labels
// describe the shuttle height relative to the net (above / slightly above /
// slightly below / below) instead of stroke-technique names (overhead /
// shoulder / underhand / scoop). The stored enum values
// (overhead/side/underhand/scoop, high -> low) are unchanged; only the
// user-facing labels change. Highest maps to "above the net", lowest to
// "below the net".
type Dict = Record<string, any>
const jaE = (ja as Dict).enrichment
const enE = (en as Dict).enrichment

const KEYS = [
  'contact_height_overhead',
  'contact_height_side',
  'contact_height_underhand',
  'contact_height_scoop',
] as const

describe('contact height labels describe net-relative height (F-T003-06)', () => {
  it('all four labels exist and are non-empty in both locales', () => {
    for (const k of KEYS) {
      expect(typeof jaE[k]).toBe('string')
      expect(typeof enE[k]).toBe('string')
      expect(jaE[k].length).toBeGreaterThan(0)
      expect(enE[k].length).toBeGreaterThan(0)
    }
  })

  it('ja labels use the requested net-relative wording', () => {
    expect(jaE.contact_height_overhead).toBe('ネットより上')
    expect(jaE.contact_height_side).toBe('ネットよりやや上')
    expect(jaE.contact_height_underhand).toBe('ネットよりやや下')
    expect(jaE.contact_height_scoop).toBe('ネットより下')
  })

  it('ja labels no longer use stroke-technique names', () => {
    const joined = KEYS.map((k) => jaE[k]).join('|')
    for (const old of ['頭上', 'サイド', 'アンダー', 'スクープ']) {
      expect(joined).not.toContain(old)
    }
  })

  it('en labels use the requested net-relative wording', () => {
    expect(enE.contact_height_overhead).toBe('Above the net')
    expect(enE.contact_height_side).toBe('Slightly above the net')
    expect(enE.contact_height_underhand).toBe('Slightly below the net')
    expect(enE.contact_height_scoop).toBe('Below the net')
  })

  it('en labels no longer use stroke-technique names', () => {
    const joined = KEYS.map((k) => enE[k].toLowerCase()).join('|')
    for (const old of ['overhead', 'shoulder', 'underhand', 'scoop']) {
      expect(joined).not.toContain(old)
    }
  })

  it('highest maps to above, lowest maps to below (net-relative ordering)', () => {
    expect(jaE.contact_height_overhead).toContain('上')
    expect(jaE.contact_height_scoop).toContain('下')
    expect(enE.contact_height_overhead.toLowerCase()).toContain('above')
    expect(enE.contact_height_scoop.toLowerCase()).toContain('below')
  })
})
