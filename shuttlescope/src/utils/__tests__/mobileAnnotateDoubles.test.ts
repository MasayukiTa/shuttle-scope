import { describe, expect, it } from 'vitest'
import { isDoublesFormat, resolveHitter, slotBelongsToTeam, slotsOfTeam } from '../mobileAnnotateDoubles'
import { serveOnlyRallyPayload } from '../mobileAnnotatePass2'
import { isConflictingRally, pruneConfirmed, type RallyKeyed } from '../mobileAnnotateRallies'

describe('mobileAnnotateDoubles', () => {
  it('detects doubles formats', () => {
    expect(isDoublesFormat('doubles_md')).toBe(true)
    expect(isDoublesFormat('doubles')).toBe(true)
    expect(isDoublesFormat('singles')).toBe(false)
    expect(isDoublesFormat(undefined)).toBe(false)
  })

  it('lists both individual slots of a team', () => {
    expect(slotsOfTeam('player_a')).toEqual(['player_a', 'partner_a'])
    expect(slotsOfTeam('player_b')).toEqual(['player_b', 'partner_b'])
  })

  it('keeps the partner slot instead of collapsing to the team value', () => {
    expect(resolveHitter(true, 'player_a', 'partner_a')).toBe('partner_a')
    expect(resolveHitter(true, 'player_b', 'partner_b')).toBe('partner_b')
  })

  it('refuses to save doubles strokes without a slot or with a slot of the other team', () => {
    expect(resolveHitter(true, 'player_a', null)).toBeNull()
    expect(resolveHitter(true, 'player_a', 'partner_b')).toBeNull()
    expect(slotBelongsToTeam('partner_b', 'player_a')).toBe(false)
  })

  it('singles keep the team value', () => {
    expect(resolveHitter(false, 'player_b', null)).toBe('player_b')
  })

  it('serve-only payload stores the chosen server slot', () => {
    const { stroke } = serveOnlyRallyPayload({ server: 'player_a' }, { serve_hit: 'BL', serve_land: 'BR' }, 'partner_a')
    expect(stroke.player).toBe('partner_a')
    expect(serveOnlyRallyPayload({ server: 'player_a' }, {}).stroke.player).toBe('player_a')
  })
})

describe('pruneConfirmed with conflicting content', () => {
  const server: RallyKeyed[] = [{ set_id: 1, rally_num: 1, winner: 'player_a', score_a_after: 1, score_b_after: 0 }]

  it('drops a local rally that the server already holds with the same content', () => {
    const local: RallyKeyed[] = [{ set_id: 1, rally_num: 1, winner: 'player_a', score_a_after: 1, score_b_after: 0 }]
    expect(pruneConfirmed(server, local)).toEqual([])
  })

  it('keeps a local rally whose winner/score differs from the server row', () => {
    const local: RallyKeyed[] = [{ set_id: 1, rally_num: 1, winner: 'player_b', score_a_after: 0, score_b_after: 1 }]
    expect(pruneConfirmed(server, local)).toBe(local)
    expect(isConflictingRally(server[0], local[0])).toBe(true)
  })

  it('treats rows without content fields as confirmed (key only)', () => {
    const local: RallyKeyed[] = [{ set_id: 1, rally_num: 1 }]
    expect(pruneConfirmed(server, local)).toEqual([])
  })
})
