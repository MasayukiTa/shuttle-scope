import { describe, it, expect } from 'vitest'
import { fmtPct, isFiniteNumber } from '../format'

describe('fmtPct', () => {
  it('formats finite ratios', () => {
    expect(fmtPct(0.5)).toBe('50.0%')
    expect(fmtPct(0)).toBe('0.0%')
    expect(fmtPct(0.12345, 2)).toBe('12.35%')
  })
  it('returns an em dash instead of NaN% for missing / non-finite values', () => {
    expect(fmtPct(undefined)).toBe('—')
    expect(fmtPct(null)).toBe('—')
    expect(fmtPct(NaN)).toBe('—')
    expect(fmtPct(Infinity)).toBe('—')
    expect(fmtPct('0.5' as unknown as number)).toBe('—')
  })
  it('isFiniteNumber', () => {
    expect(isFiniteNumber(1)).toBe(true)
    expect(isFiniteNumber(NaN)).toBe(false)
    expect(isFiniteNumber(null)).toBe(false)
  })
})
