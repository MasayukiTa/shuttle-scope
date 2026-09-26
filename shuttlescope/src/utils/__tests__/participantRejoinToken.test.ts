import { beforeEach, describe, expect, it } from 'vitest'
import {
  clearParticipantRejoinToken,
  getParticipantRejoinToken,
  setParticipantRejoinToken,
} from '../participantRejoinToken'

describe('participantRejoinToken', () => {
  beforeEach(() => {
    sessionStorage.clear()
  })

  it('persists a participant proof for the same tab', () => {
    setParticipantRejoinToken('ABCD12', 'device-1', 'token-value')
    expect(getParticipantRejoinToken('ABCD12', 'device-1')).toBe('token-value')
  })

  it('normalizes the session code but keeps devices isolated', () => {
    setParticipantRejoinToken(' abcd12 ', 'device-1', 'token-a')
    expect(getParticipantRejoinToken('ABCD12', 'device-1')).toBe('token-a')
    expect(getParticipantRejoinToken('ABCD12', 'device-2')).toBe('')
  })

  it('can discard a stale proof without touching another session', () => {
    setParticipantRejoinToken('AAAA11', 'device-1', 'token-a')
    setParticipantRejoinToken('BBBB22', 'device-1', 'token-b')
    clearParticipantRejoinToken('AAAA11', 'device-1')
    expect(getParticipantRejoinToken('AAAA11', 'device-1')).toBe('')
    expect(getParticipantRejoinToken('BBBB22', 'device-1')).toBe('token-b')
  })
})
