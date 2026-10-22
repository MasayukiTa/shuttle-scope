import { describe, expect, it } from 'vitest'
import { canDeleteMatch, canDeletePlayer, canUseConditionPage, canWriteMatch } from '../roleAccess'

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

describe('match / player write capabilities (mirror the backend role rules)', () => {
  it('allows match registration and editing only for admin, coach and analyst', () => {
    expect(canWriteMatch('admin')).toBe(true)
    expect(canWriteMatch('coach')).toBe(true)
    expect(canWriteMatch('analyst')).toBe(true)
    expect(canWriteMatch('player')).toBe(false)
    expect(canWriteMatch('demo')).toBe(false)
  })

  it('allows match deletion only for admin and analyst', () => {
    expect(canDeleteMatch('admin')).toBe(true)
    expect(canDeleteMatch('analyst')).toBe(true)
    expect(canDeleteMatch('coach')).toBe(false)
    expect(canDeleteMatch('player')).toBe(false)
    expect(canDeleteMatch('demo')).toBe(false)
  })

  it('allows player deletion only for admin and analyst', () => {
    expect(canDeletePlayer('admin')).toBe(true)
    expect(canDeletePlayer('analyst')).toBe(true)
    expect(canDeletePlayer('coach')).toBe(false)
    expect(canDeletePlayer('player')).toBe(false)
  })

  it('leaves an unresolved role to the server', () => {
    expect(canWriteMatch(null)).toBe(true)
    expect(canDeleteMatch(undefined)).toBe(true)
    expect(canDeletePlayer(null)).toBe(true)
  })
})
