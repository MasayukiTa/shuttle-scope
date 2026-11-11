/**
 * draft/ 行の snapshot からの送信 (固定条件: snapshot から buildBatchPayload で送る)。
 *
 * IndexedDB の draft/ 行は snapshot だけを持ち payload を持たない。自動再送はこの
 * snapshot から buildBatchPayloadFromDraftSnapshot で /strokes/batch 本文を組み立てて送るが、
 * それは snapshot が確定済みラリーと同じ必須フィールド (winner / endType / スコア) を
 * 備えている場合に限る。入力途中 (未確定) の snapshot は winner がなく、送らず残る。
 */
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { IDBFactory } from 'fake-indexeddb'

import {
  buildBatchPayloadFromDraftSnapshot,
} from '../annotationPayload'
import {
  listDraftsForMatch,
  removeDraftRally,
  stashDraftRally,
} from '../offlineStrokeQueue'
import type { StrokeInput } from '@/types'

const USER = 2
const MATCH = 6

beforeEach(() => {
  globalThis.indexedDB = new IDBFactory()
})

afterEach(() => {
  globalThis.indexedDB = new IDBFactory()
})

const stroke: StrokeInput = {
  stroke_num: 1,
  player: 'player_a',
  shot_type: 'clear',
  is_backhand: false,
  is_around_head: false,
}

/** 確定済み snapshot (winner / endType / スコアが揃う)。 */
function confirmedSnapshot() {
  return {
    setId: 15,
    rallyNum: 29,
    strokes: [stroke],
    winner: 'player_a' as const,
    endType: 'ace',
    scoreAAfter: 11,
    scoreBAfter: 9,
    rallyStartTimestamp: 1.5,
    isBasicMode: true,
  }
}

/** 入力途中 snapshot (AnnotatorPage の autosave data 相当: winner なし)。 */
function draftSnapshot() {
  return {
    setId: 15,
    rallyNum: 29,
    strokes: [stroke],
    pendingStroke: {},
    inputStep: 'shot_type',
    rallyStartTimestamp: 1.5,
    currentPlayer: 'player_a',
  }
}

describe('buildBatchPayloadFromDraftSnapshot', () => {
  it('確定済み snapshot は /strokes/batch 本文を返す', () => {
    const payload = buildBatchPayloadFromDraftSnapshot(confirmedSnapshot())
    expect(payload).not.toBeNull()
    expect(payload?.rally).toMatchObject({
      set_id: 15,
      rally_num: 29,
      winner: 'player_a',
      end_type: 'ace',
      score_a_after: 11,
      score_b_after: 9,
    })
    expect(payload?.strokes).toHaveLength(1)
  })

  it('入力途中 (winner なし) snapshot は null を返す', () => {
    expect(buildBatchPayloadFromDraftSnapshot(draftSnapshot())).toBeNull()
  })

  it('endType 欠落・スコア欠落・strokes非配列は null', () => {
    const base = confirmedSnapshot()
    expect(buildBatchPayloadFromDraftSnapshot({ ...base, endType: '' })).toBeNull()
    expect(buildBatchPayloadFromDraftSnapshot({ ...base, scoreAAfter: Number.NaN })).toBeNull()
    expect(buildBatchPayloadFromDraftSnapshot({ ...base, strokes: null })).toBeNull()
    expect(buildBatchPayloadFromDraftSnapshot(null)).toBeNull()
    expect(buildBatchPayloadFromDraftSnapshot('x')).toBeNull()
  })
})

describe('listDraftsForMatch + snapshot 送信の最小再現', () => {
  async function resendDrafts(
    matchId: number,
    ownerUserId: number,
    post: (body: unknown) => Promise<{ success: boolean }>,
  ): Promise<number> {
    const drafts = await listDraftsForMatch(matchId, ownerUserId)
    let sent = 0
    for (const d of drafts) {
      const payload = buildBatchPayloadFromDraftSnapshot(d.snapshot)
      if (payload == null) continue
      const res = await post(payload)
      if (res.success) {
        await removeDraftRally(ownerUserId, d.matchId, d.setId, d.rallyNum)
        sent += 1
      }
    }
    return sent
  }

  it('未確定 draft は送らず残る', async () => {
    await stashDraftRally({
      ownerUserId: USER,
      matchId: MATCH,
      setId: 15,
      rallyNum: 29,
      snapshot: draftSnapshot(),
      updated_at: '2026-11-10T00:00:00Z',
    })
    const sentBodies: unknown[] = []
    const sent = await resendDrafts(MATCH, USER, async (b) => { sentBodies.push(b); return { success: true } })
    expect(sent).toBe(0)
    expect(sentBodies).toHaveLength(0)
    // 残っている
    expect((await listDraftsForMatch(MATCH, USER)).map((d) => d.rallyNum)).toEqual([29])
  })

  it('確定済み snapshot の draft は本文付きで送られ、送信成功で消える', async () => {
    await stashDraftRally({
      ownerUserId: USER,
      matchId: MATCH,
      setId: 15,
      rallyNum: 29,
      snapshot: confirmedSnapshot(),
      updated_at: '2026-11-10T00:00:00Z',
    })
    const sentBodies: unknown[] = []
    const sent = await resendDrafts(MATCH, USER, async (b) => { sentBodies.push(b); return { success: true } })
    expect(sent).toBe(1)
    expect(sentBodies[0]).toMatchObject({ rally: { rally_num: 29, winner: 'player_a' } })
    expect(await listDraftsForMatch(MATCH, USER)).toHaveLength(0)
  })

  it('他人 (別 owner) の draft は読まない', async () => {
    await stashDraftRally({
      ownerUserId: USER + 1,
      matchId: MATCH,
      setId: 15,
      rallyNum: 29,
      snapshot: confirmedSnapshot(),
      updated_at: '2026-11-10T00:00:00Z',
    })
    expect(await listDraftsForMatch(MATCH, USER)).toHaveLength(0)
  })
})
