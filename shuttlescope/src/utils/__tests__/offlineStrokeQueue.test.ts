import { describe, expect, it } from 'vitest'

import {
  offlineStrokeIdempotencyKey,
  offlineStrokeQueueKey,
  pendingRallyBelongsTo,
} from '../offlineStrokeQueue'

describe('offlineStrokeQueue ownership', () => {
  it('scopes persistence and idempotency keys by authenticated user', () => {
    expect(offlineStrokeQueueKey(11, 22, 33, 44)).toBe('11/22/33/44')
    expect(offlineStrokeQueueKey(12, 22, 33, 44)).toBe('12/22/33/44')

    expect(offlineStrokeIdempotencyKey(11, 22, 33, 44))
      .toBe('offline-11-22-33-44')
    expect(offlineStrokeIdempotencyKey(12, 22, 33, 44))
      .toBe('offline-12-22-33-44')
  })

  it('does not auto-claim legacy ownerless rows', () => {
    const legacy = {
      matchId: 22,
      setId: 33,
      rallyNum: 44,
      payload: {},
      queued_at: '2026-09-27T00:00:00Z',
    }

    expect(pendingRallyBelongsTo(legacy, 11, 22)).toBe(false)
  })

  it('never replays another user queue row for the same match', () => {
    const queued = {
      ownerUserId: 11,
      matchId: 22,
      setId: 33,
      rallyNum: 44,
      payload: {},
      queued_at: '2026-09-27T00:00:00Z',
    }

    expect(pendingRallyBelongsTo(queued, 11, 22)).toBe(true)
    expect(pendingRallyBelongsTo(queued, 12, 22)).toBe(false)
    expect(pendingRallyBelongsTo(queued, 11, 23)).toBe(false)
  })
})
