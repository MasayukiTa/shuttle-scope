import { describe, expect, it } from 'vitest'
import {
  decideUndoPending,
  finalHitterFor,
  mergeRallies,
  planLiveStart,
  pruneConfirmed,
  resolveNextServer,
  shouldReinitFromServer,
} from '../mobileAnnotateRallies'

const R = (set_id: number, rally_num: number, extra: Record<string, unknown> = {}) => ({
  set_id,
  rally_num,
  client_uuid: '',
  winner: 'player_a' as const,
  ...extra,
})

describe('mergeRallies', () => {
  it('keeps one copy when the server and the local pending rally are the same rally', () => {
    // サーバの uuid は送信キューの clientUuid と別の値。uuid が違っても 1 件にする。
    const server = [R(1, 1, { id: 10, client_uuid: 'server-uuid' })]
    const local = [R(1, 1, { id: null, client_uuid: 'queue-uuid', pending: true })]
    const out = mergeRallies(server, local)
    expect(out).toHaveLength(1)
    expect(out[0].id).toBe(10)
  })

  it('keeps unsent rallies and sorts by set then rally number', () => {
    const server = [R(2, 1, { id: 3 }), R(1, 2, { id: 2 }), R(1, 1, { id: 1 })]
    const local = [R(1, 3, { id: null, client_uuid: 'a' }), R(1, 3, { id: null, client_uuid: 'b' })]
    const out = mergeRallies(server, local)
    expect(out.map((r) => `${r.set_id}-${r.rally_num}`)).toEqual(['1-1', '1-2', '1-3', '2-1'])
  })
})

describe('pruneConfirmed', () => {
  it('drops the local rally once the server has it', () => {
    const local = [R(1, 1, { client_uuid: 'x' }), R(1, 2, { client_uuid: 'y' })]
    expect(pruneConfirmed([R(1, 1, { id: 5 })], local).map((r) => r.rally_num)).toEqual([2])
  })

  it('returns the same array when nothing changed', () => {
    const local = [R(1, 2)]
    expect(pruneConfirmed([R(1, 1)], local)).toBe(local)
  })
})

describe('resolveNextServer', () => {
  const sets = [
    { id: 11, set_num: 1 },
    { id: 12, set_num: 2 },
  ]

  it('uses the match initial server for the very first rally', () => {
    expect(
      resolveNextServer({ rallies: [], sets, currentSetId: 11, matchInitialServer: 'player_b' }),
    ).toBe('player_b')
  })

  it('returns null, not player_a, when nothing is known', () => {
    expect(resolveNextServer({ rallies: [], sets, currentSetId: 11, matchInitialServer: null })).toBeNull()
    expect(resolveNextServer({ rallies: [], sets, currentSetId: 11, matchInitialServer: 'x' })).toBeNull()
  })

  it('uses the winner of the last rally in the same set', () => {
    const rallies = [R(11, 1, { winner: 'player_a' }), R(11, 2, { winner: 'player_b' })]
    expect(resolveNextServer({ rallies, sets, currentSetId: 11, matchInitialServer: 'player_a' })).toBe('player_b')
  })

  it('starts a new set with the winner of the previous set', () => {
    const rallies = [R(11, 1, { winner: 'player_a' }), R(11, 2, { winner: 'player_b' })]
    expect(resolveNextServer({ rallies, sets, currentSetId: 12, matchInitialServer: 'player_a' })).toBe('player_b')
  })
})

describe('finalHitterFor', () => {
  it('is the winner for a winning shot and the loser for an opponent error', () => {
    expect(finalHitterFor({ winner: 'player_a' }, 'winner_shot')).toBe('player_a')
    expect(finalHitterFor({ winner: 'player_a' }, 'opponent_error')).toBe('player_b')
    expect(finalHitterFor({ winner: 'player_b' }, 'opponent_error')).toBe('player_a')
  })
})

describe('decideUndoPending', () => {
  it('removes locally only when the queue item was cancelled', () => {
    expect(decideUndoPending('cancelled', null)).toBe('remove_local')
  })
  it('keeps the rally while it is being sent', () => {
    expect(decideUndoPending('inflight', null)).toBe('keep_busy')
  })
  it('deletes the server copy when the item was already sent', () => {
    expect(decideUndoPending('not_found', 42)).toBe('enqueue_delete')
    expect(decideUndoPending('not_found', null)).toBe('remove_local')
  })
})

describe('planLiveStart', () => {
  const state = { current_set_num: 2, current_rally_num: 15, score_a: 9, score_b: 5, next_server: 'player_b' as const }

  it('restores rally number, score and server from the server state', () => {
    const plan = planLiveStart(state, [
      { id: 2, set_num: 2 },
      { id: 1, set_num: 1 },
    ])
    expect(plan).toMatchObject({ setNum: 2, rallyNum: 15, scoreA: 9, scoreB: 5, server: 'player_b' })
    // 配列の末尾 (set_num 1) ではなく set_num で探す
    expect(plan.set).toEqual({ id: 2, set_num: 2 })
  })

  it('reports a missing set and an unknown server instead of guessing', () => {
    const plan = planLiveStart({ ...state, next_server: null }, [{ id: 1, set_num: 1 }])
    expect(plan.set).toBeNull()
    expect(plan.server).toBeNull()
  })
})

describe('shouldReinitFromServer', () => {
  const base = { matchId: 1, currentSetId: 2, pendingSaveCount: 0, saveErrorCount: 0 }
  it('reinitializes for a different match or set', () => {
    expect(shouldReinitFromServer({ ...base, matchId: 9 }, 1, 2)).toBe(true)
    expect(shouldReinitFromServer(base, 1, 3)).toBe(true)
  })
  it('keeps the screen state while saves are pending or failed', () => {
    expect(shouldReinitFromServer({ ...base, pendingSaveCount: 1 }, 1, 2)).toBe(false)
    expect(shouldReinitFromServer({ ...base, saveErrorCount: 1 }, 1, 2)).toBe(false)
  })
  it('takes the server state when nothing is unsaved', () => {
    expect(shouldReinitFromServer(base, 1, 2)).toBe(true)
  })
})
