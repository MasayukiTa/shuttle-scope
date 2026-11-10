import { describe, it, expect } from 'vitest'
import { wasSkippedForNoUser } from '../analytics'

describe('wasSkippedForNoUser', () => {
  it('is true only for the unauthenticated skip response', () => {
    expect(wasSkippedForNoUser({ success: true, inserted: 0, skipped: 'no_user' })).toBe(true)
  })
  it('is false for a normal insert and for other skip reasons', () => {
    expect(wasSkippedForNoUser({ success: true, inserted: 3 })).toBe(false)
    expect(wasSkippedForNoUser({ success: true, inserted: 0, skipped: 'internal' })).toBe(false)
  })
  it('is false for non-object bodies', () => {
    expect(wasSkippedForNoUser(null)).toBe(false)
    expect(wasSkippedForNoUser(undefined)).toBe(false)
    expect(wasSkippedForNoUser('no_user')).toBe(false)
  })
})
