import { describe, expect, it } from 'vitest'
import { MAX_QUEUED_EVENTS, QUEUE_TTL_MS, pickPruneIds, planFlush } from '../analytics'

const ev = (id: string, ts: number, owner?: string | null) => ({ event_id: id, client_ts: ts, owner })

describe('pickPruneIds', () => {
  const now = 1_000_000_000_000

  it('drops events older than the TTL and keeps the rest', () => {
    const ids = pickPruneIds([ev('old', now - QUEUE_TTL_MS - 1), ev('edge', now - QUEUE_TTL_MS), ev('new', now)], now)
    expect(ids).toEqual(['old'])
  })

  it('drops the oldest events beyond the max count', () => {
    const events = [ev('c', now - 1), ev('a', now - 3), ev('b', now - 2)]
    expect(pickPruneIds(events, now, QUEUE_TTL_MS, 2)).toEqual(['a'])
  })

  it('does nothing for an empty or small queue', () => {
    expect(pickPruneIds([], now)).toEqual([])
    expect(pickPruneIds([ev('a', now)], now)).toEqual([])
    expect(MAX_QUEUED_EVENTS).toBeGreaterThan(0)
  })
})

describe('planFlush (owner boundary, same rule as offlineStrokeQueue)', () => {
  it('sends only the current user\'s events and keeps another user\'s events (never discarded, never sent under the current user)', () => {
    const plan = planFlush([ev('a1', 1, 'A'), ev('b1', 2, 'B'), ev('b2', 3, 'B')], 'B')
    expect(plan.send.map(e => e.event_id)).toEqual(['b1', 'b2'])
    // A\'s event is neither sent under B nor dropped: it stays for A.
    expect(plan.dropIds).toEqual([])
  })

  it('A -> logout -> B regression: B\'s flush never carries A\'s events', () => {
    const queued = [ev('a1', 1, 'A'), ev('a2', 2, 'A'), ev('b1', 3, 'B')]
    const plan = planFlush(queued, 'B')
    expect(plan.send.map(e => e.event_id)).toEqual(['b1'])
    expect(plan.send.some(e => e.owner === 'A')).toBe(false)
    expect(plan.dropIds).toEqual([])
  })

  it('A can send its own backlog after logging back in (kept for that owner)', () => {
    const queued = [ev('a1', 1, 'A'), ev('a2', 2, 'A'), ev('b1', 3, 'B')]
    const plan = planFlush(queued, 'A')
    expect(plan.send.map(e => e.event_id)).toEqual(['a1', 'a2'])
    expect(plan.dropIds).toEqual([])
  })

  it('sends events recorded before login (no owner) as before', () => {
    const plan = planFlush([ev('pre', 1, null), ev('legacy', 2, undefined)], 'B')
    expect(plan.send.map(e => e.event_id)).toEqual(['pre', 'legacy'])
    expect(plan.dropIds).toEqual([])
  })

  it('while logged out, owner-tagged events are kept (not sent, not dropped); unowned are sent', () => {
    const plan = planFlush([ev('a1', 1, 'A'), ev('pre', 2, null)], null)
    expect(plan.send.map(e => e.event_id)).toEqual(['pre'])
    expect(plan.send.some(e => e.owner === 'A')).toBe(false)
    expect(plan.dropIds).toEqual([])
  })

  it('does not let a foreign backlog starve the current user\'s batch', () => {
    const foreign = Array.from({ length: 150 }, (_, i) => ev(`a${i}`, i, 'A'))
    const plan = planFlush([...foreign, ev('b1', 999, 'B')], 'B', 100)
    expect(plan.send.map(e => e.event_id)).toEqual(['b1'])
    expect(plan.dropIds).toEqual([])
  })

  it('caps the batch size', () => {
    const events = Array.from({ length: 10 }, (_, i) => ev(`e${i}`, i, 'B'))
    expect(planFlush(events, 'B', 4).send).toHaveLength(4)
  })
})
