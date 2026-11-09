import { describe, expect, it } from 'vitest'

import { buildBatchPayload, buildMidRallyPayload } from '@/utils/annotationPayload'
import type { StrokeInput } from '@/types'

/**
 * fix/midrally-save-v3: 途中保存 (mid-rally autosave) フラグのユニットテスト。
 *
 * - 確定時 (buildBatchPayload) は replace_strokes=true / final=true を付ける。
 *   これで途中保存 (final=false) が先に入っていても確定時に全打球へ置き換わる。
 * - 途中保存 (buildMidRallyPayload) は replace_strokes=true / final=false。
 * - どちらも打球数が rally_length と strokes に正しく反映される。
 */
const baseStroke: StrokeInput = {
  stroke_num: 1,
  player: 'player_a',
  shot_type: 'short_service',
  hit_zone: 'MC',
  hit_zone_source: 'cv',
  hit_zone_cv_original: 'MC',
  land_zone: 'NL',
  is_backhand: false,
  is_around_head: false,
  above_net: true,
  timestamp_sec: 12.5,
  return_quality: 'attack',
  contact_height: 'overhead',
  contact_zone: 'rear',
  movement_burden: 'medium',
  movement_direction: 'forward',
}

function strokesOf(n: number): StrokeInput[] {
  return Array.from({ length: n }, (_, i) => ({
    ...baseStroke,
    stroke_num: i + 1,
    player: i % 2 === 0 ? 'player_a' : 'player_b',
  }))
}

const baseArgs = {
  setId: 1,
  rallyNum: 3,
  winner: 'player_a' as const,
  endType: 'winner',
  scoreAAfter: 5,
  scoreBAfter: 4,
  rallyStartTimestamp: 100,
  isBasicMode: true,
}

describe('mid-rally autosave payload flags', () => {
  it('buildBatchPayload は確定保存として replace_strokes=true / final=true を付ける', () => {
    const p = buildBatchPayload({ ...baseArgs, strokes: strokesOf(6) })
    expect(p.replace_strokes).toBe(true)
    expect(p.final).toBe(true)
    expect(p.strokes).toHaveLength(6)
    expect(p.rally.rally_length).toBe(6)
  })

  it('buildMidRallyPayload は途中保存として replace_strokes=true / final=false を付ける', () => {
    const p = buildMidRallyPayload({ ...baseArgs, strokes: strokesOf(3) })
    expect(p.replace_strokes).toBe(true)
    expect(p.final).toBe(false)
    expect(p.strokes).toHaveLength(3)
    expect(p.rally.rally_length).toBe(3)
  })

  it('途中3本→確定6本で、確定ペイロードは6本・final=trueになる', () => {
    const mid = buildMidRallyPayload({ ...baseArgs, strokes: strokesOf(3) })
    const fin = buildBatchPayload({ ...baseArgs, strokes: strokesOf(6) })
    expect(mid.final).toBe(false)
    expect(mid.strokes).toHaveLength(3)
    expect(fin.final).toBe(true)
    expect(fin.strokes).toHaveLength(6)
    // 同じ (set_id, rally_num) を対象にしている (置き換え対象が一致)
    expect(fin.rally.set_id).toBe(mid.rally.set_id)
    expect(fin.rally.rally_num).toBe(mid.rally.rally_num)
  })
})
