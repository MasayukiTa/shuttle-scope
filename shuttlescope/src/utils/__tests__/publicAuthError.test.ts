import { describe, expect, it } from 'vitest'
import { publicAuthErrorKey } from '@/utils/publicAuthError'

const http = (status: number, message = 'raw backend text') =>
  Object.assign(new Error(message), { status })

describe('publicAuthErrorKey', () => {
  it('treats an error without status as a network failure', () => {
    expect(publicAuthErrorKey(new Error('Failed to fetch'), 'register')).toBe('auth.public_error.network')
  })

  it('maps status to a stable key and never depends on the message text', () => {
    expect(publicAuthErrorKey(http(429), 'register')).toBe('auth.public_error.rate_limited')
    expect(publicAuthErrorKey(http(503), 'register')).toBe('auth.public_error.unavailable')
    expect(publicAuthErrorKey(http(500, '{"detail":"x"}'), 'invitation_accept')).toBe('auth.public_error.server')
    expect(publicAuthErrorKey(http(409), 'invitation_accept')).toBe('auth.public_error.conflict')
    expect(publicAuthErrorKey(http(422), 'register')).toBe('auth.public_error.invalid_input')
    expect(publicAuthErrorKey(http(418), 'register')).toBe('auth.public_error.unknown')
  })

  it('separates 400 by screen: invalid input for register, invalid/expired for invitations', () => {
    expect(publicAuthErrorKey(http(400), 'register')).toBe('auth.public_error.invalid_input')
    expect(publicAuthErrorKey(http(400), 'invitation_peek')).toBe('auth.public_error.invitation_invalid')
    expect(publicAuthErrorKey(http(400), 'invitation_accept')).toBe('auth.public_error.invitation_invalid')
  })
})
