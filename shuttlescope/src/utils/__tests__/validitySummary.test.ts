import { describe, expect, it } from 'vitest'
import { hasValiditySummary } from '../validitySummary'

describe('hasValiditySummary', () => {
  it('is false when there is nothing to show', () => {
    expect(hasValiditySummary(null)).toBe(false)
    expect(hasValiditySummary(undefined)).toBe(false)
    expect(hasValiditySummary({})).toBe(false)
    expect(hasValiditySummary({ valid_ratio: null, flags: null })).toBe(false)
    expect(hasValiditySummary({ valid_ratio: null, flags: [] })).toBe(false)
  })

  it('is true for a ratio, including 0, or for flags', () => {
    expect(hasValiditySummary({ valid_ratio: 0.8 })).toBe(true)
    expect(hasValiditySummary({ valid_ratio: 0 })).toBe(true)
    expect(hasValiditySummary({ valid_ratio: null, flags: ['straight_line'] })).toBe(true)
  })
})
