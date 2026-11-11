/**
 * mid-rally autosave (ラリー確定前の中間保存) が確定ラリーを上書きしないことを
 * 実 DB (fake-indexeddb) で検証する。
 *
 * 欠陥 (merge 済 ec7a99e7):
 *   mid-rally autosave が確定ラリーと同じ owned 枠
 *   (offlineStrokeQueueKey = `<owner>/<match>/<set>/<rally>`) に final=false の
 *   中間 payload で退避していたため:
 *     (a) 確定ラリーの退避行を中間 payload が上書きし、useOfflineSync が
 *         それを確定として送る。
 *     (b) 中間保存送信成功後の removeRallyAfterSave が同じ owned キーを消し、
 *         先に退避してあった確定ラリーの行まで消す。
 *     (c) 中間保存が確定と同じ冪等キー (offline-...) を使い、応答が確定を
 *         先取りする。
 *
 * 修正: mid-rally は別 prefix (mid/) の行に退避し、isNonSendableKey で非送信扱いに
 * なる。冪等キーも offline-mid-... と分ける。
 *
 * この試験はタイマー・送信を全モックした実装の写しではなく、**実 DB に
 * 確定前の mid 行が残った状態で sync (再送ループ) を走らせ**、確定の内容が
 * 上書きされないことを確かめる。
 */
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { IDBFactory } from 'fake-indexeddb'

import {
  countPendingForUserStrict,
  isNonSendableKey,
  listPendingForMatch,
  listPendingForUserStrict,
  midRallyIdempotencyKey,
  midRallyQueueKey,
  offlineStrokeIdempotencyKey,
  offlineStrokeQueueKey,
  removeMidRally,
  removePending,
  stashDraftRally,
  stashMidRally,
  stashPending,
} from '../offlineStrokeQueue'

const USER = 3
const MATCH = 9
const SET = 2
const RALLY = 7

beforeEach(() => {
  globalThis.indexedDB = new IDBFactory()
})

afterEach(() => {
  globalThis.indexedDB = new IDBFactory()
})

/** useOfflineSync の送信ループを模した最小再現。listPendingForMatch が返す
 *  行だけを、本文 (payload) 付きで安定冪等キーで post する
 *  (useOfflineSync.ts の送信部と同じ選別・キー生成)。 */
async function runSync(
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

const midPayload = { rally: { set_id: SET, rally_num: RALLY }, strokes: [{ stroke_num: 1 }], final: false }
const finalPayload = { rally: { set_id: SET, rally_num: RALLY }, strokes: [{ stroke_num: 1 }, { stroke_num: 2 }], final: true }

describe('mid-rally autosave が確定ラリーを上書きしない', () => {
  it('(1) mid 行と確定行が別キーに入り、互いを上書きしない', async () => {
    await stashMidRally(USER, {
      matchId: MATCH, setId: SET, rallyNum: RALLY,
      payload: midPayload, queued_at: '2026-11-11T00:00:00Z',
    })
    await stashPending({
      ownerUserId: USER, matchId: MATCH, setId: SET, rallyNum: RALLY,
      payload: finalPayload, queued_at: '2026-11-11T00:00:01Z',
    })
    // 別 prefix なのでキーが衝突しない。
    expect(midRallyQueueKey(USER, MATCH, SET, RALLY)).not.toBe(
      offlineStrokeQueueKey(USER, MATCH, SET, RALLY),
    )
  })

  it('(1) 確定前に mid 行が残った状態で sync を走らせても、送るのは確定 payload だけ', async () => {
    // 中間保存が先に退避されている。
    await stashMidRally(USER, {
      matchId: MATCH, setId: SET, rallyNum: RALLY,
      payload: midPayload, queued_at: '2026-11-11T00:00:00Z',
    })
    // その後ラリーが確定し、確定行が owned 枠に入る。
    await stashPending({
      ownerUserId: USER, matchId: MATCH, setId: SET, rallyNum: RALLY,
      payload: finalPayload, queued_at: '2026-11-11T00:00:01Z',
    })

    // listPendingForMatch に mid 行は出ず、確定行だけが出る。
    const pending = await listPendingForMatch(MATCH, USER)
    expect(pending).toHaveLength(1)
    expect((pending[0].payload as { final?: boolean }).final).toBe(true)

    const sent: Array<{ body: unknown; key: string }> = []
    const post = async (_p: string, body: unknown, headers: Record<string, string>) => {
      sent.push({ body, key: headers['X-Idempotency-Key'] })
      return { success: true }
    }
    await runSync(MATCH, USER, post)

    // 確定 payload が 1 件、確定の冪等キーで送られている (mid は送られない)。
    expect(sent).toHaveLength(1)
    expect((sent[0].body as { final?: boolean }).final).toBe(true)
    expect(sent[0].key).toBe(offlineStrokeIdempotencyKey(USER, MATCH, SET, RALLY))
    expect(sent[0].key).not.toBe(midRallyIdempotencyKey(USER, MATCH, SET, RALLY))
  })

  it('(1) mid の冪等キーは確定の冪等キーを先取りしない (別キー)', () => {
    expect(midRallyIdempotencyKey(USER, MATCH, SET, RALLY)).toBe(`offline-mid-${USER}-${MATCH}-${SET}-${RALLY}`)
    expect(offlineStrokeIdempotencyKey(USER, MATCH, SET, RALLY)).toBe(`offline-${USER}-${MATCH}-${SET}-${RALLY}`)
    expect(midRallyIdempotencyKey(USER, MATCH, SET, RALLY)).not.toBe(
      offlineStrokeIdempotencyKey(USER, MATCH, SET, RALLY),
    )
  })

  it('(2) removeMidRally は mid 行だけを消し、確定 owned 行を消さない', async () => {
    await stashMidRally(USER, {
      matchId: MATCH, setId: SET, rallyNum: RALLY,
      payload: midPayload, queued_at: '2026-11-11T00:00:00Z',
    })
    await stashPending({
      ownerUserId: USER, matchId: MATCH, setId: SET, rallyNum: RALLY,
      payload: finalPayload, queued_at: '2026-11-11T00:00:01Z',
    })

    // 中間保存の送信成功後に mid 行を消す。
    await removeMidRally(USER, MATCH, SET, RALLY)

    // 確定 owned 行は残っている (消されていない)。
    const pending = await listPendingForMatch(MATCH, USER)
    expect(pending).toHaveLength(1)
    expect((pending[0].payload as { final?: boolean }).final).toBe(true)
  })

  it('(3) listPendingForUserStrict / countPendingForUserStrict は draft 行と mid 行を除外する', async () => {
    // draft 行 (payload 無し、snapshot のみ)。
    await stashDraftRally({
      ownerUserId: USER, matchId: MATCH, setId: SET, rallyNum: 5,
      snapshot: { strokes: [{ stroke_num: 1 }] }, updated_at: '2026-11-11T00:00:00Z',
    })
    // mid 行。
    await stashMidRally(USER, {
      matchId: MATCH, setId: SET, rallyNum: 6,
      payload: midPayload, queued_at: '2026-11-11T00:00:00Z',
    })
    // 確定 owned 行。これだけが strict/count の対象。
    await stashPending({
      ownerUserId: USER, matchId: MATCH, setId: SET, rallyNum: 7,
      payload: finalPayload, queued_at: '2026-11-11T00:00:01Z',
    })

    const strict = await listPendingForUserStrict(USER)
    expect(strict).toHaveLength(1)
    expect(strict[0].rallyNum).toBe(7)
    expect(await countPendingForUserStrict(USER)).toBe(1)
  })

  it('isNonSendableKey: mid/ キーを非送信扱いにする (draft/ unowned/ と同様)', () => {
    expect(isNonSendableKey(midRallyQueueKey(USER, MATCH, SET, RALLY))).toBe(true)
    expect(isNonSendableKey(offlineStrokeQueueKey(USER, MATCH, SET, RALLY))).toBe(false)
  })
})
