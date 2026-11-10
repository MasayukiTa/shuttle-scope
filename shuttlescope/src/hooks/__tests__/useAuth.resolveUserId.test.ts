import { describe, expect, it } from 'vitest'
import { resolveUserId } from '../useAuth'

function jwt(payload: Record<string, unknown>): string {
  const b64 = (o: unknown) => btoa(JSON.stringify(o)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
  return `${b64({ alg: 'HS256', typ: 'JWT' })}.${b64(payload)}.sig`
}

describe('resolveUserId', () => {
  it('uses the stored id when it is a positive integer', () => {
    expect(resolveUserId('17', jwt({ sub: '99' }))).toBe(17)
  })

  it('falls back to the token when nothing is stored (a tab that logged in before the id was stored)', () => {
    expect(resolveUserId(null, jwt({ sub: '42' }))).toBe(42)
    expect(resolveUserId('', jwt({ sub: 42 }))).toBe(42)
  })

  it('never turns "unknown" into a shared owner 0', () => {
    // /auth/me without user_id is stored as 0. That must not become user 0
    expect(resolveUserId('0', null)).toBeNull()
    expect(resolveUserId('0', jwt({ role: 'analyst' }))).toBeNull()
    expect(resolveUserId('-3', null)).toBeNull()
    expect(resolveUserId('abc', null)).toBeNull()
  })

  it('uses the token when the stored value is the placeholder 0', () => {
    expect(resolveUserId('0', jwt({ sub: '8' }))).toBe(8)
  })

  it('is null without any usable source', () => {
    expect(resolveUserId(null, null)).toBeNull()
    expect(resolveUserId(null, 'not-a-jwt')).toBeNull()
  })
})
