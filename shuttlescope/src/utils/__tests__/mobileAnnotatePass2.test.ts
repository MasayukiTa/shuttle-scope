import { describe, expect, it } from 'vitest'
import { serveOnlyRallyPayload } from '@/utils/mobileAnnotatePass2'

describe('serveOnlyRallyPayload', () => {
  it('builds one serve stroke and rally_length=1 for a one-stroke rally', () => {
    const out = serveOnlyRallyPayload(
      { server: 'player_b' },
      { serve_hit: 'BC', serve_land: 'MR' },
    )
    expect(out.rallyLength).toBe(1)
    expect(out.stroke).toEqual({
      stroke_num: 1,
      player: 'player_b',
      shot_type: 'serve',
      hit_zone: 'BC',
      land_zone: 'MR',
      source_method: 'manual',
      hit_zone_source: 'manual',
    })
  })

  it('records a hand-entered stroke as manual, and omits hit_zone_source without a hit zone', () => {
    const noHit = serveOnlyRallyPayload({ server: 'player_a' }, { serve_land: 'MR' })
    expect(noHit.stroke.source_method).toBe('manual')
    expect('hit_zone_source' in noHit.stroke).toBe(false)
  })

  it('never emits the 9999 final sentinel', () => {
    const out = serveOnlyRallyPayload({ server: 'player_a' }, { serve_hit: 'BL', serve_land: 'NC' })
    expect(JSON.stringify(out)).not.toContain('9999')
    expect(JSON.stringify(out)).not.toContain('__final_pending')
  })
})
