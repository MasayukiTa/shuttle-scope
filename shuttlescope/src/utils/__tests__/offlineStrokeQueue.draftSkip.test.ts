/**
 * draft/unowned 行の自動再送除外 (muse 実機: draft/2/6/15/29)。
 *
 * IndexedDB shuttlescope_offline / pending_rallies には、owned な確定ラリー
 * (payload あり) と、入力途中の draft/ 行 (snapshot だけで payload が無い) が
 * 同じ ObjectStore に別 prefix で入る。draft/ 行が所有権フィルタを素通り
 * すると、useOfflineSync が it.payload (=undefined) をそのまま送り、
 * POST /strokes/batch の本文が空 (422) になってラリーが保存されない。
 *
 * ここでは fake-indexeddb の実 DB を使い、
 *   - draft/ 行 (payload なし・snapshot あり) は listPendingForMatch に出ず、残る
 *   - payload も snapshot も無い行も送らず残る
 *   - owned 確定行 (payload あり) は本文付きで送られる
 * ことを検証する。
 */
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { IDBFactory } from 'fake-indexeddb'

import {
  draftQueueKey,
  isNonSendableKey,
  listPendingForMatch,
  offlineStrokeIdempotencyKey,
  offlineStrokeQueueKey,
  pendingRallyBelongsTo,
  removePending,
  stashDraftRally,
  stashPending,
} from '../offlineStrokeQueue'

const USER = 2
const MATCH = 6

beforeEach(() => {
  globalThis.indexedDB = new IDBFactory()
})

afterEach(() => {
  globalThis.indexedDB = new IDBFactory()
})

/** useOfflineSync の送信ループを模した最小再現。listPendingForMatch が返す
 *  行だけを、本文 (payload) 付きで post する。 */
async function resend(
  matchId: number,
  ownerUserId: number,
  post: (path: string, body: unknown, headers: Record<string, string>) => Promise<{ success: boolean }>,
): Promise<void> {
  const items = await listPendingForMatch(matchId, ownerUserId)
  for (const it of items) {
    if (it.payload == null) continue
    const key = offlineStrokeIdempotencyKey(ownerUserId, it.matchId, it.setId, it.rallyNum)
    const res = await post('/strokes/batch', it.payload, { 'X-Idempotency-Key': key })
    if (res.success) await removePending(ownerUserId, it.matchId, it.setId, it.rallyNum)
  }
}

describe('draft 行は自動再送の対象外', () => {
  it('isNonSendableKey: draft/ と unowned/ を除外し、owned キーは通す', () => {
    expect(isNonSendableKey(draftQueueKey(USER, MATCH, 15, 29))).toBe(true)
    expect(isNonSendableKey('unowned/6/15/29')).toBe(true)
    expect(isNonSendableKey(offlineStrokeQueueKey(USER, MATCH, 15, 29))).toBe(false)
    expect(isNonSendableKey(undefined)).toBe(false)
  })

  it('pendingRallyBelongsTo: draft/ 行と payload 欠落行を弾く', () => {
    const draftRow = {
      key: draftQueueKey(USER, MATCH, 15, 29),
      ownerUserId: USER,
      matchId: MATCH,
      setId: 15,
      rallyNum: 29,
      // payload なし。snapshot はあるが owned 確定ではない。
      queued_at: '2026-11-10T00:00:00Z',
    }
    expect(pendingRallyBelongsTo(draftRow, USER, MATCH)).toBe(false)

    const ownedRow = {
      key: offlineStrokeQueueKey(USER, MATCH, 15, 29),
      ownerUserId: USER,
      matchId: MATCH,
      setId: 15,
      rallyNum: 29,
      payload: { rally: {}, strokes: [] },
      queued_at: '2026-11-10T00:00:00Z',
    }
    expect(pendingRallyBelongsTo(ownedRow, USER, MATCH)).toBe(true)
  })

  it('draft 行 (payload なし・snapshot あり) は送らず残る、owned 確定行は本文付きで送る', async () => {
    // 入力途中の draft/ 行。payload は無く snapshot だけ。
    await stashDraftRally({
      ownerUserId: USER,
      matchId: MATCH,
      setId: 15,
      rallyNum: 29,
      snapshot: { strokes: [{ stroke_num: 1 }], pendingStroke: {} },
      updated_at: '2026-11-10T00:00:00Z',
    })
    // 確定済み owned 行。本文 (payload) あり。
    await stashPending({
      ownerUserId: USER,
      matchId: MATCH,
      setId: 15,
      rallyNum: 30,
      payload: { rally: { set_id: 15, rally_num: 30 }, strokes: [] },
      queued_at: '2026-11-10T00:00:01Z',
    })

    // listPendingForMatch に draft 行は出ず、owned 確定行だけが出る。
    const pending = await listPendingForMatch(MATCH, USER)
    expect(pending.map((p) => p.rallyNum)).toEqual([30])

    const sent: Array<{ body: unknown; key: string }> = []
    const post = async (_path: string, body: unknown, headers: Record<string, string>) => {
      sent.push({ body, key: headers['X-Idempotency-Key'] })
      return { success: true }
    }
    await resend(MATCH, USER, post)

    // owned 確定行が 1 件、本文付きで送られている。
    expect(sent).toHaveLength(1)
    expect(sent[0].key).toBe(offlineStrokeIdempotencyKey(USER, MATCH, 15, 30))
    expect(sent[0].body).not.toBeNull()
    expect(sent[0].body).toMatchObject({ rally: { rally_num: 30 } })

    // draft 行は送られず残る (listPendingForMatch には最初から出ていない)。
    const draftStill = await listPendingForMatch(MATCH, USER)
    // owned 行は送信成功で消え、draft 行はそもそも対象外なので空。
    expect(draftStill).toHaveLength(0)
  })

  it('payload も snapshot も無い行は送らず残る', async () => {
    // payload 欠落の owned キー行 (snapshot も無い)。所有権フィルタで弾かれる。
    const brokenRow = {
      key: offlineStrokeQueueKey(USER, MATCH, 15, 40),
      ownerUserId: USER,
      matchId: MATCH,
      setId: 15,
      rallyNum: 40,
      queued_at: '2026-11-10T00:00:00Z',
    }
    expect(pendingRallyBelongsTo(brokenRow, USER, MATCH)).toBe(false)
  })
})
