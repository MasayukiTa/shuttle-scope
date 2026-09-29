import { describe, expect, it } from 'vitest'
import {
  classifyQueueHttpFailure,
  nextSequenceRunnableAt,
  queueSequenceKey,
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
