import { describe, it, expect } from 'vitest'
import { isConditionImprovement } from '../conditionDirection'

describe('isConditionImprovement (監査 #348)', () => {
  it('CCS improves when it rises', () => {
    expect(isConditionImprovement('ccs', 5)).toBe(true)
    expect(isConditionImprovement('ccs', -5)).toBe(false)
  })

  it('F1-F5 and Hooper Index improve when they fall (higher = worse)', () => {
    for (const key of ['f1', 'f2', 'f3', 'f4', 'f5', 'hooper_index']) {
      expect(isConditionImprovement(key, -3)).toBe(true)
      expect(isConditionImprovement(key, 3)).toBe(false)
    }
  })

  it('no change is not treated as a decline', () => {
    expect(isConditionImprovement('ccs', 0)).toBe(true)
    expect(isConditionImprovement('hooper_index', 0)).toBe(true)
  })
})
