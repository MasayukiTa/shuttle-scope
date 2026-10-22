import { describe, expect, it } from 'vitest'
import { canUseConditionPage } from '../roleAccess'

describe('canUseConditionPage', () => {
  it('hides the Condition page from the read-only demo role', () => {
    expect(canUseConditionPage('demo')).toBe(false)
  })

  it.each(['admin', 'analyst', 'coach', 'player'] as const)('keeps it for %s', (role) => {
    expect(canUseConditionPage(role)).toBe(true)
  })

  it('does not change the behaviour for an unresolved role', () => {
    expect(canUseConditionPage(null)).toBe(true)
    expect(canUseConditionPage(undefined)).toBe(true)
  })
})
