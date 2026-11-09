import { describe, it, expect } from 'vitest'
import {
  isZoneCode,
  pickLandZoneSuggestion,
  buildLandZoneSuggestions,
} from '../mobileAnnotateCvSuggest'

describe('isZoneCode', () => {
  it('accepts all 9 valid Zone9 codes', () => {
    for (const z of ['BL', 'BC', 'BR', 'ML', 'MC', 'MR', 'NL', 'NC', 'NR']) {
      expect(isZoneCode(z)).toBe(true)
    }
  })

  it('rejects out-of-vocabulary / 18-zone / OB / net labels', () => {
    for (const z of ['A_front_left', 'OB_LL', 'NET_L', 'bl', 'XX', '', 'B']) {
      expect(isZoneCode(z)).toBe(false)
    }
  })

  it('rejects non-string values', () => {
    expect(isZoneCode(null)).toBe(false)
    expect(isZoneCode(undefined)).toBe(false)
    expect(isZoneCode(5)).toBe(false)
    expect(isZoneCode({})).toBe(false)
  })
})

describe('pickLandZoneSuggestion', () => {
  it('returns the zone for an auto_filled candidate', () => {
    expect(
      pickLandZoneSuggestion({ value: 'BR', confidence_score: 0.9, decision_mode: 'auto_filled' }),
    ).toBe('BR')
  })

  it('returns the zone for a suggested candidate', () => {
    expect(
      pickLandZoneSuggestion({ value: 'MC', confidence_score: 0.5, decision_mode: 'suggested' }),
    ).toBe('MC')
  })

  it('drops review_required candidates regardless of confidence', () => {
    expect(
      pickLandZoneSuggestion({ value: 'BL', confidence_score: 0.99, decision_mode: 'review_required' }),
    ).toBeNull()
  })

  it('drops candidates whose value is outside the Zone9 vocabulary', () => {
    expect(
      pickLandZoneSuggestion({ value: 'A_front_left', confidence_score: 0.9, decision_mode: 'auto_filled' }),
    ).toBeNull()
    expect(
      pickLandZoneSuggestion({ value: 'NET_L', confidence_score: 0.9, decision_mode: 'suggested' }),
    ).toBeNull()
  })

  it('drops null / empty candidates', () => {
    expect(pickLandZoneSuggestion(null)).toBeNull()
    expect(pickLandZoneSuggestion(undefined)).toBeNull()
    expect(pickLandZoneSuggestion({})).toBeNull()
    expect(pickLandZoneSuggestion({ value: null })).toBeNull()
  })

  it('enforces minConfidence when provided', () => {
    const land = { value: 'NR', confidence_score: 0.4, decision_mode: 'suggested' }
    expect(pickLandZoneSuggestion(land, { minConfidence: 0.5 })).toBeNull()
    expect(pickLandZoneSuggestion(land, { minConfidence: 0.3 })).toBe('NR')
  })

  it('drops candidates missing a numeric confidence when minConfidence is set', () => {
    expect(
      pickLandZoneSuggestion({ value: 'NR', decision_mode: 'suggested' }, { minConfidence: 0.5 }),
    ).toBeNull()
  })

  it('ignores minConfidence of 0 (does not require a confidence score)', () => {
    expect(
      pickLandZoneSuggestion({ value: 'NR', decision_mode: 'suggested' }, { minConfidence: 0 }),
    ).toBe('NR')
  })
})

describe('buildLandZoneSuggestions', () => {
  it('returns an empty map for null / undefined / empty rally', () => {
    expect(buildLandZoneSuggestions(null).size).toBe(0)
    expect(buildLandZoneSuggestions(undefined).size).toBe(0)
    expect(buildLandZoneSuggestions({}).size).toBe(0)
    expect(buildLandZoneSuggestions({ strokes: [] }).size).toBe(0)
  })

  it('maps stroke_num -> zone only for acceptable candidates', () => {
    const rally = {
      strokes: [
        { stroke_num: 1, land_zone: { value: 'BR', confidence_score: 0.9, decision_mode: 'auto_filled' } },
        { stroke_num: 2, land_zone: { value: 'MC', confidence_score: 0.5, decision_mode: 'suggested' } },
        { stroke_num: 3, land_zone: { value: 'NL', confidence_score: 0.99, decision_mode: 'review_required' } },
        { stroke_num: 4, land_zone: { value: 'A_front_left', confidence_score: 0.9, decision_mode: 'auto_filled' } },
        { stroke_num: 5, land_zone: null },
      ],
    }
    const m = buildLandZoneSuggestions(rally)
    expect(m.size).toBe(2)
    expect(m.get(1)).toBe('BR')
    expect(m.get(2)).toBe('MC')
    expect(m.has(3)).toBe(false)
    expect(m.has(4)).toBe(false)
    expect(m.has(5)).toBe(false)
  })

  it('ignores strokes without an integer stroke_num', () => {
    const rally = {
      strokes: [
        { stroke_num: undefined, land_zone: { value: 'BR', decision_mode: 'auto_filled' } },
        { stroke_num: 1.5, land_zone: { value: 'MC', decision_mode: 'auto_filled' } },
        { land_zone: { value: 'NL', decision_mode: 'auto_filled' } },
      ],
    }
    expect(buildLandZoneSuggestions(rally).size).toBe(0)
  })

  it('keeps the first candidate when a stroke_num is duplicated', () => {
    const rally = {
      strokes: [
        { stroke_num: 1, land_zone: { value: 'BL', decision_mode: 'auto_filled' } },
        { stroke_num: 1, land_zone: { value: 'BR', decision_mode: 'auto_filled' } },
      ],
    }
    const m = buildLandZoneSuggestions(rally)
    expect(m.get(1)).toBe('BL')
  })

  it('applies minConfidence across the rally', () => {
    const rally = {
      strokes: [
        { stroke_num: 1, land_zone: { value: 'BR', confidence_score: 0.8, decision_mode: 'auto_filled' } },
        { stroke_num: 2, land_zone: { value: 'MC', confidence_score: 0.45, decision_mode: 'suggested' } },
      ],
    }
    const m = buildLandZoneSuggestions(rally, { minConfidence: 0.6 })
    expect(m.size).toBe(1)
    expect(m.get(1)).toBe('BR')
  })

  it('handles a null entry inside the strokes array', () => {
    const rally = { strokes: [null, { stroke_num: 1, land_zone: { value: 'NR', decision_mode: 'suggested' } }] }
    const m = buildLandZoneSuggestions(rally as never)
    expect(m.size).toBe(1)
    expect(m.get(1)).toBe('NR')
  })
})
