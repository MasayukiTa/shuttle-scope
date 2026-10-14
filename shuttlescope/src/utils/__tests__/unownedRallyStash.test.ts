/**
 * S-14: ユーザー ID が本当に不明な間に保存へ失敗したラリーは、失われず、誰のものにもならない。
 *
 * fake-indexeddb は依存に無いので、offlineStrokeQueue が使う最小限の IndexedDB
 * (open / objectStore の put・delete・getAll / transaction の oncomplete) を差し替える。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  claimUnownedForMatch,
  countPendingForUser,
  discardUnownedForMatch,
  listPendingForMatch,
  listUnownedForMatch,
  removeRallyAfterSave,
  stashRallyBeforeSave,
} from '../offlineStrokeQueue'

type Row = Record<string, unknown> & { key: string }
let rows: Map<string, Row>

function installFakeIndexedDb() {
  rows = new Map()
  const store = {
    put(v: Row) {
      const req: { onsuccess?: () => void; result?: unknown } = {}
      rows.set(v.key, JSON.parse(JSON.stringify(v)))
      return req
    },
    delete(k: string) {
      rows.delete(k)
      return {}
    },
    getAll() {
      const req: { onsuccess?: () => void; onerror?: () => void; result?: unknown } = {}
      req.result = [...rows.values()].map((r) => JSON.parse(JSON.stringify(r)))
      queueMicrotask(() => req.onsuccess?.())
      return req
    },
  }
  const db = {
    objectStoreNames: { contains: () => true },
    createObjectStore: () => store,
    close: () => undefined,
    transaction: () => {
      const tx: { oncomplete?: () => void; onerror?: () => void; objectStore: () => typeof store } = {
        objectStore: () => store,
      }
      queueMicrotask(() => queueMicrotask(() => tx.oncomplete?.()))
      return tx
    },
  }
  vi.stubGlobal('indexedDB', {
    open: () => {
      const req: { onsuccess?: () => void; onupgradeneeded?: () => void; result?: unknown } = {}
      req.result = db
      queueMicrotask(() => req.onsuccess?.())
      return req
    },
  })
}

const MATCH = 22
const rally = (setId: number, rallyNum: number) => ({
  matchId: MATCH,
  setId,
  rallyNum,
  payload: { rally_num: rallyNum },
  queued_at: `2026-10-14T00:00:0${rallyNum}Z`,
})

describe('S-14 所有者不明の退避', () => {
  beforeEach(() => {
    installFakeIndexedDb()
  })

  it('ID が不明なら所有者不明の枠に残り、ユーザー 0 にも他のユーザーにも帰属しない', async () => {
    const slot = await stashRallyBeforeSave(null, rally(1, 1))
    expect(slot).toBe('unowned')

    // 失われていない
    expect(await listUnownedForMatch(MATCH)).toHaveLength(1)
    // ユーザー 0 / 任意のユーザーの枠には入っていない
    expect(await listPendingForMatch(MATCH, 0)).toEqual([])
    expect(await listPendingForMatch(MATCH, 7)).toEqual([])
    expect(await countPendingForUser(0)).toBe(0)
    expect(await countPendingForUser(7)).toBe(0)
    // 保存された行は所有者を持たない
    const saved = [...rows.values()]
    expect(saved).toHaveLength(1)
    expect(saved[0].key.startsWith('unowned/')).toBe(true)
    expect('ownerUserId' in saved[0]).toBe(false)
  })

  it('ID が分かっていれば従来どおり本人の枠に入る', async () => {
    expect(await stashRallyBeforeSave(5, rally(1, 1))).toBe('owned')
    expect(await listPendingForMatch(MATCH, 5)).toHaveLength(1)
    expect(await listUnownedForMatch(MATCH)).toEqual([])
  })

  it('後からログインした別のユーザーには自動で渡らない (一覧にも件数にも出ない)', async () => {
    await stashRallyBeforeSave(null, rally(1, 1))
    // useOfflineSync が使う一覧は所有者付きの行だけ
    expect(await listPendingForMatch(MATCH, 8)).toEqual([])
    expect(await countPendingForUser(8)).toBe(0)
    // 明示確認なしでは移らない
    expect(await listUnownedForMatch(MATCH)).toHaveLength(1)
  })

  it('不正な ID (0 / NaN / 負) では確認操作でも移らない', async () => {
    await stashRallyBeforeSave(null, rally(1, 1))
    expect(await claimUnownedForMatch(MATCH, 0)).toBe(0)
    expect(await claimUnownedForMatch(MATCH, Number.NaN)).toBe(0)
    expect(await claimUnownedForMatch(MATCH, -3)).toBe(0)
    expect(await listUnownedForMatch(MATCH)).toHaveLength(1)
    expect(await listPendingForMatch(MATCH, 0)).toEqual([])
  })

  it('明示確認 (claim) をしたユーザーのものにだけなり、別のユーザーには出ない', async () => {
    await stashRallyBeforeSave(null, rally(1, 1))
    await stashRallyBeforeSave(null, rally(1, 2))
    expect(await claimUnownedForMatch(MATCH, 8)).toBe(2)

    expect(await listUnownedForMatch(MATCH)).toEqual([])
    expect(await listPendingForMatch(MATCH, 8)).toHaveLength(2)
    expect(await listPendingForMatch(MATCH, 9)).toEqual([])
  })

  it('破棄すると残らない', async () => {
    await stashRallyBeforeSave(null, rally(1, 1))
    expect(await discardUnownedForMatch(MATCH)).toBe(1)
    expect(await listUnownedForMatch(MATCH)).toEqual([])
    expect(rows.size).toBe(0)
  })

  it('保存成功後は入れた枠だけを消す (本人の枠は触らない)', async () => {
    await stashRallyBeforeSave(null, rally(1, 1))
    await stashRallyBeforeSave(5, rally(1, 1))
    await removeRallyAfterSave(null, MATCH, 1, 1)
    expect(await listUnownedForMatch(MATCH)).toEqual([])
    expect(await listPendingForMatch(MATCH, 5)).toHaveLength(1)
  })
})
