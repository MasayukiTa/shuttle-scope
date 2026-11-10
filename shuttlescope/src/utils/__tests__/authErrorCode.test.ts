import { describe, expect, it } from 'vitest'
import { shouldRestartMfaLogin } from '@/utils/authErrorCode'

describe('shouldRestartMfaLogin', () => {
  it('restarts only on 401 with a token-gone error code', () => {
    expect(shouldRestartMfaLogin(401, 'MFA_TOKEN_INVALID_OR_EXPIRED')).toBe(true)
    expect(shouldRestartMfaLogin(401, 'TOKEN_INVALID_OR_EXPIRED')).toBe(true)
  })

  it('keeps the MFA step when the code was merely mistyped (401 without a code)', () => {
    expect(shouldRestartMfaLogin(401, null)).toBe(false)
    expect(shouldRestartMfaLogin(401, undefined)).toBe(false)
    expect(shouldRestartMfaLogin(401, 'OTHER')).toBe(false)
  })

  it('ignores the code on non-401 statuses and does not depend on message text', () => {
    expect(shouldRestartMfaLogin(429, 'MFA_TOKEN_INVALID_OR_EXPIRED')).toBe(false)
    expect(shouldRestartMfaLogin(500, null)).toBe(false)
  })
})
