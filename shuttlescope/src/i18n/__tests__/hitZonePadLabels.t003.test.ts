import { describe, it, expect } from 'vitest'
import ja from '../ja.json'
import en from '../en.json'

// F-T003-06 (part 2): customer request #8 states that "打点"
// (contact height) describes a height, not a place, and must not be used to
// label where a shot happened. The hit-zone keypad pad headings used to read
// "打点: トップ行" / "Hit zone:". Those pads let the annotator pick which of
// the 9 court cells (a location) the stroke was played from, so the heading
// must read as a location. We reuse the canonical shot-location label
// (annotator.hit_zone = 打球位置 / Shot location) for both locales.
type Dict = Record<string, unknown>
const jaAnnotator = (ja as Dict).annotator as Dict
const enAnnotator = (en as Dict).annotator as Dict
const jaUi = jaAnnotator.ui as Dict
const enUi = enAnnotator.ui as Dict

const HINT_KEYS = ['hit_zone_hint_doubles', 'hit_zone_hint_singles'] as const

describe('F-T003-06 hit-zone pad headings use a location word, not 打点', () => {
  it('hint labels exist and are non-empty in both locales', () => {
    for (const k of HINT_KEYS) {
      expect(typeof jaUi[k]).toBe('string')
      expect(typeof enUi[k]).toBe('string')
      expect((jaUi[k] as string).length).toBeGreaterThan(0)
      expect((enUi[k] as string).length).toBeGreaterThan(0)
    }
  })

  it('ja hint labels no longer contain the height word 打点', () => {
    for (const k of HINT_KEYS) {
      expect(jaUi[k] as string).not.toContain('打点')
    }
  })

  it('en hint labels no longer contain "Hit zone"', () => {
    for (const k of HINT_KEYS) {
      expect((enUi[k] as string).toLowerCase()).not.toContain('hit zone')
    }
  })

  it('ja hint labels reuse the canonical shot-location word 打球位置', () => {
    expect(jaAnnotator.hit_zone).toBe('打球位置')
    for (const k of HINT_KEYS) {
      expect(jaUi[k] as string).toContain('打球位置')
    }
  })

  it('en hint labels reuse the canonical shot-location word "Shot location"', () => {
    expect(enAnnotator.hit_zone).toBe('Shot location')
    for (const k of HINT_KEYS) {
      expect((enUi[k] as string).toLowerCase()).toContain('shot location')
    }
  })
})
