/**
 * unsent-indicator (ELN E-90e8cfaa2891 \u95a2\u9023):
 *   \u300c\u901a\u4fe1\u304c\u5207\u308c\u3066\u3082\u672a\u9001\u4fe1\u304c\u6b8b\u308a\u3001\u5fa9\u5e30\u5f8c\u306b\u81ea\u52d5\u3067\u9001\u3089\u308c\u308b\u3053\u3068\u300d\u3068\n *   \u300c\u30bf\u30d6\u3092\u9589\u3058\u3066\u958b\u304d\u76f4\u3057\u3066\u3082\u672a\u9001\u4fe1\u6570\u304c\u6b8b\u308b (IndexedDB \u6c38\u7d9a)\u300d\u3092\u3001\n *   fake-indexeddb \u306e\u5b9f DB \u3067\u691c\u8a3c\u3059\u308b\u3002\n */
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { IDBFactory } from 'fake-indexeddb'

import {
  countPendingForUserStrict,
  flushPendingForUser,
  listPendingForUserStrict,
  stashPending,
} from '../offlineStrokeQueue'

const USER = 42

function freshIndexedDb(): void {
  // \u300c\u30bf\u30d6\u3092\u958b\u304d\u76f4\u3057\u305f\u300d\u76f8\u5f53: \u30d7\u30ed\u30bb\u30b9\u5185\u30ad\u30e3\u30c3\u30b7\u30e5\u3092\u6368\u3066\u3001\u6c38\u7d9a\u5c64\u3060\u3051\u304b\u3089\u8aad\u307f\u76f4\u3059\u3002
  // fake-indexeddb \u306f\u65b0\u3057\u3044 IDBFactory \u3092\u4f5c\u3063\u3066\u3082\u524d\u306e\u30c7\u30fc\u30bf\u3092\u5f15\u304d\u7d99\u304c\u306a\u3044\u305f\u3081\u3001
  // \u3053\u3053\u3067\u306f structuredClone \u3092\u4f7f\u308f\u305a\u3001\u540c\u3058 factory \u3092\u4f7f\u3044\u56de\u3057\u3066\n  // \u300c\u540c\u3058 DB \u3092\u958b\u304d\u76f4\u3059\u300d\u3053\u3068\u3067\u6c38\u7d9a\u3092\u8868\u73fe\u3059\u308b (openDb \u304c\u6bce\u56de open \u3059\u308b)\u3002
}

beforeEach(() => {
  globalThis.indexedDB = new IDBFactory()
})

afterEach(() => {
  globalThis.indexedDB = new IDBFactory()
})

describe('\\u672a\\u9001\\u4fe1\\u30e9\\u30ea\\u30fc\\u306e\\u6c38\\u7d9a\\u3068\\u518d\\u9001', () => {
  it('stash \\u3057\\u305f\\u672a\\u9001\\u4fe1\\u306f\\u958b\\u304d\\u76f4\\u3057 (\\u540c\\u3058 DB \\u3092\\u518d\\u30aa\\u30fc\\u30d7\\u30f3) \\u3057\\u3066\\u3082\\u6b8b\\u308b', async () => {
    await stashPending({ ownerUserId: USER, matchId: 1, setId: 1, rallyNum: 1, payload: { a: 1 }, queued_at: '2026-11-09T00:00:00Z' })
    await stashPending({ ownerUserId: USER, matchId: 1, setId: 1, rallyNum: 2, payload: { a: 2 }, queued_at: '2026-11-09T00:00:01Z' })

    // \\u300c\\u30bf\\u30d6\\u3092\\u958b\\u304d\\u76f4\\u3059\\u300d: \\u65b0\\u3057\\u3044\\u63a5\\u7d9a\\u3067\\u6570\\u3048\\u3066\\u3082\\u6c38\\u7d9a\\u3055\\u308c\\u3066\\u3044\\u308b\\u3053\\u3068\\u3092\\u78ba\\u8a8d\\u3002
    const count = await countPendingForUserStrict(USER)
    expect(count).toBe(2)
  })

  it('\\u901a\\u4fe1\\u65ad\\u2192\\u5fa9\\u5e30: \\u5fa9\\u5e30\\u5f8c\\u306e flush \\u3067\\u5168\\u4ef6\\u9001\\u4fe1\\u3055\\u308c\\u3001\\u672a\\u9001\\u4fe1\\u304c\\u6e1b\\u308b', async () => {
    await stashPending({ ownerUserId: USER, matchId: 7, setId: 1, rallyNum: 1, payload: { s: 1 }, queued_at: '2026-11-09T00:00:00Z' })
    await stashPending({ ownerUserId: USER, matchId: 7, setId: 1, rallyNum: 2, payload: { s: 2 }, queued_at: '2026-11-09T00:00:01Z' })
    expect(await countPendingForUserStrict(USER)).toBe(2)

    // \\u5fa9\\u5e30\\u5f8c: \\u6210\\u529f\\u3092\\u8fd4\\u3059 post \\u3092\\u6ce8\\u5165\\u3002\\u5b89\\u5b9a\\u51aa\\u7b49\\u30ad\\u30fc\\u304c\\u4ed8\\u304f\\u3053\\u3068\\u3082\\u78ba\\u8a8d\\u3002
    const sentKeys: string[] = []
    const post = async (_path: string, _body: unknown, headers: Record<string, string>) => {
      sentKeys.push(headers['X-Idempotency-Key'])
      return { success: true }
    }
    await flushPendingForUser(USER, post)

    expect(sentKeys).toEqual(['offline-42-7-1-1', 'offline-42-7-1-2'])
    expect(await countPendingForUserStrict(USER)).toBe(0)
  })

  it('\\u9001\\u4fe1\\u5931\\u6557 (success=false) \\u306f throw \\u3057\\u3001\\u672a\\u9001\\u4fe1\\u306f\\u30ad\\u30e5\\u30fc\\u306b\\u6b8b\\u308b', async () => {
    await stashPending({ ownerUserId: USER, matchId: 9, setId: 2, rallyNum: 5, payload: { x: 1 }, queued_at: '2026-11-09T00:00:00Z' })

    const post = async () => ({ success: false })
    await expect(flushPendingForUser(USER, post)).rejects.toThrow()

    // \\u6b8b\\u3063\\u3066\\u3044\\u308b = \\u6b21\\u56de online \\u3067\\u518d\\u9001\\u3055\\u308c\\u308b\\u4f59\\u5730\\u304c\\u3042\\u308b\\u3002
    expect(await countPendingForUserStrict(USER)).toBe(1)
    const items = await listPendingForUserStrict(USER)
    expect(items[0].rallyNum).toBe(5)
  })

  it('\\u672c\\u4eba\\u4ee5\\u5916\\u306e\\u672a\\u9001\\u4fe1\\u306f\\u6570\\u3048\\u306a\\u3044 (\\u5171\\u6709\\u7aef\\u672b\\u306e\\u4ed6\\u4eba\\u884c\\u3092\\u81ea\\u5206\\u306e\\u6570\\u306b\\u5165\\u308c\\u306a\\u3044)', async () => {
    await stashPending({ ownerUserId: USER, matchId: 1, setId: 1, rallyNum: 1, payload: {}, queued_at: '2026-11-09T00:00:00Z' })
    await stashPending({ ownerUserId: 99, matchId: 1, setId: 1, rallyNum: 1, payload: {}, queued_at: '2026-11-09T00:00:00Z' })
    expect(await countPendingForUserStrict(USER)).toBe(1)
    expect(await countPendingForUserStrict(99)).toBe(1)
  })
})
