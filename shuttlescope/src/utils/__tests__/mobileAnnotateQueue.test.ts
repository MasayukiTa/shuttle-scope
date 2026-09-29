import { describe, expect, it } from 'vitest'
import {
  classifyQueueHttpFailure,
  nextSequenceRunnableAt,
  queueFlushDecision,
  queueItemOwnership,
  queueSequenceKey,
  tokenUserId,
  type QueueItem,
  type QueueEndpoint,
} from '../mobileAnnotateQueue'

function item(
  localId: number,
  endpoint: QueueEndpoint,
  pathParams: Record<string, string | number> | undefined,
  nextAttemptAt: number,
  overrides: Partial<QueueItem> = {},
): QueueItem {
  return {
    localId,
    clientUuid: `item-${localId}`,
    endpoint,
    pathParams,
    attempts: 0,
    nextAttemptAt,
    manualRetry: false,
    queuedAt: localId,
    ...overrides,
  }
}

describe('mobileAnnotateQueue HTTP failure classification', () => {
  it('waits for authentication on 401 instead of poisoning the queue', () => {
    expect(classifyQueueHttpFailure(401)).toBe('auth')
  })

  it('keeps permission and validation failures manual', () => {
    expect(classifyQueueHttpFailure(403)).toBe('manual')
    expect(classifyQueueHttpFailure(422)).toBe('manual')
  })

  it('retries throttling and server failures', () => {
    expect(classifyQueueHttpFailure(429)).toBe('retry')
    expect(classifyQueueHttpFailure(500)).toBe('retry')
    expect(classifyQueueHttpFailure(503)).toBe('retry')
  })
})

describe('mobileAnnotateQueue per-rally ordering', () => {
  it('derives the same sequence key for stroke creation and rally updates', () => {
    expect(queueSequenceKey(
      item(1, 'POST /api/strokes?rally_id=:rally_id', { rally_id: 42 }, 0),
    )).toBe('rally:42')
    expect(queueSequenceKey(
      item(2, 'PUT /api/rallies/:id', { id: 42 }, 0),
    )).toBe('rally:42')
  })

  it('supports an explicit rally sequence for stroke updates whose URL lacks rally_id', () => {
    const update = item(
      3,
      'PUT /api/strokes/:id',
      { id: 99 },
      0,
      { sequenceKey: 'rally:42' },
    )
    expect(queueSequenceKey(update)).toBe('rally:42')
  })

  it('does not schedule a later same-rally child ahead of a backed-off parent', () => {
    const items = [
      item(1, 'POST /api/strokes?rally_id=:rally_id', { rally_id: 42 }, 10_000),
      item(2, 'PUT /api/rallies/:id', { id: 42 }, 0),
    ]
    expect(nextSequenceRunnableAt(items)).toBe(10_000)
  })

  it('lets an independent rally proceed while another rally is backed off', () => {
    const items = [
      item(1, 'POST /api/strokes?rally_id=:rally_id', { rally_id: 42 }, 10_000),
      item(2, 'PUT /api/rallies/:id', { id: 42 }, 0),
      item(3, 'POST /api/strokes?rally_id=:rally_id', { rally_id: 84 }, 500),
    ]
    expect(nextSequenceRunnableAt(items)).toBe(500)
  })

  it('a manual parent blocks only its own rally sequence', () => {
    const blocked = [
      item(1, 'POST /api/strokes?rally_id=:rally_id', { rally_id: 42 }, 0, {
        manualRetry: true,
      }),
      item(2, 'PUT /api/rallies/:id', { id: 42 }, 0),
    ]
    expect(nextSequenceRunnableAt(blocked)).toBeNull()

    const withIndependent = [
      ...blocked,
      item(3, 'PUT /api/rallies/:id', { id: 84 }, 700),
    ]
    expect(nextSequenceRunnableAt(withIndependent)).toBe(700)
  })
})

function jwt(payload: Record<string, unknown>): string {
  const b64 = (o: unknown) => btoa(JSON.stringify(o)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
  return `${b64({ alg: 'HS256', typ: 'JWT' })}.${b64(payload)}.sig`
}

describe('mobileAnnotateQueue owner scoping (shared device)', () => {
  it('reads the user from the same token that is sent', () => {
    expect(tokenUserId(jwt({ sub: '17' }))).toBe(17)
    expect(tokenUserId(jwt({ sub: 17 }))).toBe(17)
  })

  it('does not guess an owner from a malformed or ownerless token', () => {
    expect(tokenUserId(null)).toBeNull()
    expect(tokenUserId('not-a-jwt')).toBeNull()
    expect(tokenUserId(jwt({ sub: 'abc' }))).toBeNull()
    expect(tokenUserId(jwt({ role: 'analyst' }))).toBeNull()
    expect(tokenUserId(jwt({ sub: 0 }))).toBeNull()
  })

  it('never sends queued input of user A under user B', () => {
    const a = item(1, 'POST /api/strokes?rally_id=:rally_id', { rally_id: 42 }, 0, { ownerUserId: 11 })
    expect(queueItemOwnership(a, 11)).toBe('mine')
    expect(queueItemOwnership(a, 12)).toBe('foreign')
    expect(queueItemOwnership(a, null)).toBe('foreign')
    expect(queueFlushDecision(a, 12)).toBe('skip')
    expect(queueFlushDecision(a, null)).toBe('skip')
    expect(queueFlushDecision(a, 11)).toBe('send')
  })

  it('holds ownerless input for a manual retry instead of claiming it', () => {
    const legacy = item(2, 'PUT /api/rallies/:id', { id: 42 }, 0)
    expect(queueItemOwnership(legacy, 11)).toBe('legacy')
    expect(queueFlushDecision(legacy, 11)).toBe('hold')
    expect(queueFlushDecision(legacy, null)).toBe('hold')
  })

  it('the backlog of another user does not decide when this queue wakes up', () => {
    const items = [
      item(1, 'PUT /api/rallies/:id', { id: 42 }, 100, { ownerUserId: 11 }),
      item(2, 'PUT /api/rallies/:id', { id: 84 }, 900, { ownerUserId: 12 }),
    ]
    expect(nextSequenceRunnableAt(items, 12)).toBe(900)
    expect(nextSequenceRunnableAt(items, 11)).toBe(100)
    expect(nextSequenceRunnableAt(items, null)).toBeNull()
    // without an owner argument the previous behaviour is unchanged
    expect(nextSequenceRunnableAt(items)).toBe(100)
  })
})
