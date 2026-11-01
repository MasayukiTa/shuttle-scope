import { describe, expect, it } from 'vitest'
import { canAnnotate, canCreatePlayer, canDeleteMatch, canDeletePlayer, canUseConditionPage, canWriteMatch } from '../roleAccess'

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

  it('allows player creation (incl. tentative) only for admin and analyst', () => {
    expect(canCreatePlayer('admin')).toBe(true)
    expect(canCreatePlayer('analyst')).toBe(true)
    expect(canCreatePlayer('coach')).toBe(false)
    expect(canCreatePlayer('player')).toBe(false)
    expect(canCreatePlayer('demo')).toBe(false)
  })

  it('leaves an unresolved role to the server', () => {
    expect(canWriteMatch(null)).toBe(true)
    expect(canDeleteMatch(undefined)).toBe(true)
    expect(canDeletePlayer(null)).toBe(true)
    expect(canCreatePlayer(null)).toBe(true)
  })
})

describe('canAnnotate (mirror backend require_match_scope demo rejection)', () => {
  it('hides the annotation entry from the read-only demo role', () => {
    expect(canAnnotate('demo')).toBe(false)
  })

  it.each(['admin', 'analyst', 'coach', 'player'] as const)('keeps it for %s', (role) => {
    expect(canAnnotate(role)).toBe(true)
  })

  it('leaves an unresolved role to the server', () => {
    expect(canAnnotate(null)).toBe(true)
    expect(canAnnotate(undefined)).toBe(true)
  })
})
