import { describe, expect, it } from 'vitest'
import { hasValiditySummary } from '../validitySummary'

describe('hasValiditySummary', () => {
  it('is false when there is nothing to show', () => {
    expect(hasValiditySummary(null)).toBe(false)
    expect(hasValiditySummary(undefined)).toBe(false)
    expect(hasValiditySummary({})).toBe(false)
    expect(hasValiditySummary({ n: 0 })).toBe(false)
    expect(hasValiditySummary({ counts: null, n: null })).toBe(false)
    expect(hasValiditySummary({ counts: { ok: 0, caution: 0, unreliable: 0 }, n: 0 })).toBe(false)
  })

  it('is true when n > 0 or any count is positive', () => {
    expect(hasValiditySummary({ n: 5 })).toBe(true)
    expect(hasValiditySummary({ counts: { ok: 3, caution: 0, unreliable: 0 }, n: 0 })).toBe(true)
    expect(hasValiditySummary({ counts: { ok: 0, caution: 0, unreliable: 2 } })).toBe(true)
  })
})
