import { describe, expect, it } from 'vitest'

import { buildBatchPayload, buildSkippedRallyPayload } from '@/utils/annotationPayload'
import type { StrokeInput } from '@/types'

/**
 * /strokes/batch ペイロード構築のユニットテスト。
 *
 * 過去 dead な hooks/useAnnotation.ts が古い不完全 payload を持っていて
 * Phase A (CV override) と G2 (移動系) を黙って捨てる罠があった。
 * payload のフィールドが新規追加された際にここを更新し、
 * 「全フィールドが backend に届く」ことを構造的に担保する。
 */
describe('buildBatchPayload', () => {
  const baseStroke: StrokeInput = {
    stroke_num: 1,
    player: 'player_a',
    shot_type: 'short_service',
    hit_zone: 5,
    hit_zone_source: 'cv',
    hit_zone_cv_original: 5,
    land_zone: '7',
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

  const baseArgs = {
    setId: 1,
    rallyNum: 3,
    winner: 'player_a' as const,
    endType: 'ace',
    strokes: [baseStroke],
    scoreAAfter: 5,
    scoreBAfter: 4,
    rallyStartTimestamp: 100.0,
    isBasicMode: true,
  }

  it('rally に annotation_mode = manual_record (basic mode) を設定する', () => {
    const payload = buildBatchPayload({ ...baseArgs, isBasicMode: true })
    expect(payload.rally.annotation_mode).toBe('manual_record')
  })

  it('rally に annotation_mode = assisted_record (detailed mode) を設定する', () => {
    const payload = buildBatchPayload({ ...baseArgs, isBasicMode: false })
    expect(payload.rally.annotation_mode).toBe('assisted_record')
  })

  it('stroke の source_method が basic=manual / detailed=assisted で切り替わる', () => {
    const basic = buildBatchPayload({ ...baseArgs, isBasicMode: true })
    const detailed = buildBatchPayload({ ...baseArgs, isBasicMode: false })
    expect(basic.strokes[0].source_method).toBe('manual')
    expect(detailed.strokes[0].source_method).toBe('assisted')
  })

  it('Phase A: hit_zone_source と hit_zone_cv_original を取りこぼさない', () => {
    const overridden: StrokeInput = {
      ...baseStroke,
      hit_zone: 9,
      hit_zone_source: 'manual',
      hit_zone_cv_original: 5,
    }
    const payload = buildBatchPayload({ ...baseArgs, strokes: [overridden] })
    expect(payload.strokes[0]).toMatchObject({
      hit_zone: 9,
      hit_zone_source: 'manual',
      hit_zone_cv_original: 5,
    })
  })

  it('G2 移動系 (return_quality / contact_height / contact_zone / movement_burden / movement_direction) を取りこぼさない', () => {
    const payload = buildBatchPayload(baseArgs)
    expect(payload.strokes[0]).toMatchObject({
      return_quality: 'attack',
      contact_height: 'overhead',
      contact_zone: 'rear',
      movement_burden: 'medium',
      movement_direction: 'forward',
    })
  })

  it('basic stroke 属性 (player / shot_type / hit_zone / land_zone / is_backhand / is_around_head / above_net / timestamp_sec) を保持する', () => {
    const payload = buildBatchPayload(baseArgs)
    expect(payload.strokes[0]).toMatchObject({
      stroke_num: 1,
      player: 'player_a',
      shot_type: 'short_service',
      hit_zone: 5,
      land_zone: '7',
      is_backhand: false,
      is_around_head: false,
      above_net: true,
      timestamp_sec: 12.5,
    })
  })

  it('rally メタ (set_id / rally_num / winner / end_type / rally_length / score / video_timestamp_start) を保持する', () => {
    const payload = buildBatchPayload(baseArgs)
    expect(payload.rally).toMatchObject({
      set_id: 1,
      rally_num: 3,
      winner: 'player_a',
      end_type: 'ace',
      rally_length: 1,
      score_a_after: 5,
      score_b_after: 4,
      video_timestamp_start: 100.0,
    })
  })

  it('rally.server に最初のストロークの player を採用する', () => {
    const strokes: StrokeInput[] = [
      { ...baseStroke, stroke_num: 1, player: 'player_b' },
      { ...baseStroke, stroke_num: 2, player: 'player_a' },
    ]
    const payload = buildBatchPayload({ ...baseArgs, strokes })
    expect(payload.rally.server).toBe('player_b')
  })

  it('strokes 空配列でも rally.server は player_a fallback', () => {
    const payload = buildBatchPayload({ ...baseArgs, strokes: [] })
    expect(payload.rally.server).toBe('player_a')
    expect(payload.rally.rally_length).toBe(0)
    expect(payload.strokes).toHaveLength(0)
  })

  it('is_deuce はスコアが両方 20 以上のときに true', () => {
    expect(
      buildBatchPayload({ ...baseArgs, scoreAAfter: 19, scoreBAfter: 21 }).rally.is_deuce,
    ).toBe(false)
    expect(
      buildBatchPayload({ ...baseArgs, scoreAAfter: 20, scoreBAfter: 20 }).rally.is_deuce,
    ).toBe(true)
    expect(
      buildBatchPayload({ ...baseArgs, scoreAAfter: 22, scoreBAfter: 24 }).rally.is_deuce,
    ).toBe(true)
  })

  it('rallyStartTimestamp が null なら video_timestamp_start を undefined にする', () => {
    const payload = buildBatchPayload({ ...baseArgs, rallyStartTimestamp: null })
    expect(payload.rally.video_timestamp_start).toBeUndefined()
  })
})

/**
 * skipped ラリー (見逃し / スコア補正 / セット強制終了) ペイロード。
 * fine-tune データセット作成 / 性能評価で「アノテート済 vs 補完」を区別するため
 * annotation_mode を一貫して保存する。
 */
describe('buildSkippedRallyPayload', () => {
  const baseSkipArgs = {
    setId: 1,
    rallyNum: 5,
    server: 'player_a' as const,
    winner: 'player_b' as const,
    scoreAAfter: 3,
    scoreBAfter: 4,
    isBasicMode: true,
  }

  it('rally_length=0 / strokes=[] / is_skipped=true / end_type=skipped を出力する', () => {
    const payload = buildSkippedRallyPayload(baseSkipArgs)
    expect(payload.strokes).toEqual([])
    expect(payload.rally.rally_length).toBe(0)
    expect(payload.rally.end_type).toBe('skipped')
    // バックエンド側で is_skipped を受理するため型を緩めて確認
    expect((payload.rally as unknown as { is_skipped: boolean }).is_skipped).toBe(true)
  })

  it('annotation_mode は basic→manual_record / detailed→assisted_record', () => {
    const basic = buildSkippedRallyPayload({ ...baseSkipArgs, isBasicMode: true })
    const detailed = buildSkippedRallyPayload({ ...baseSkipArgs, isBasicMode: false })
    expect(basic.rally.annotation_mode).toBe('manual_record')
    expect(detailed.rally.annotation_mode).toBe('assisted_record')
  })

  it('server / winner / set_id / rally_num / score を保持する', () => {
    const payload = buildSkippedRallyPayload(baseSkipArgs)
    expect(payload.rally).toMatchObject({
      set_id: 1,
      rally_num: 5,
      server: 'player_a',
      winner: 'player_b',
      score_a_after: 3,
      score_b_after: 4,
    })
  })

  it('is_deuce は両者 ≥ 20 で true', () => {
    expect(
      buildSkippedRallyPayload({ ...baseSkipArgs, scoreAAfter: 19, scoreBAfter: 21 }).rally.is_deuce,
    ).toBe(false)
    expect(
      buildSkippedRallyPayload({ ...baseSkipArgs, scoreAAfter: 20, scoreBAfter: 20 }).rally.is_deuce,
    ).toBe(true)
  })
})
