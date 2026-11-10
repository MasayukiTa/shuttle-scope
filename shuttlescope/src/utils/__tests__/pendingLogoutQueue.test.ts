/**
 * G4 #529: ログアウト時の未送信ラリー処理。
 *
 * countPendingForUserStrict / flushPendingForUser / deletePendingForUser の振る舞いを
 * 検証する。fake-indexeddb は依存に無いので、既存テストと同じ構造の
 * 最小 IndexedDB スタブを差し替える。getAll を失敗させるモードも持つ。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  countPendingForUserStrict,
  deletePendingForUser,
  flushPendingForUser,
  stashRallyBeforeSave,
} from '../offlineStrokeQueue'

type Row = Record<string, unknown> & { key: string }
let rows: Map<string, Row>
let failGetAll = false

function installFakeIndexedDb() {
  rows = new Map()
  failGetAll = false
  const store = {
    put(v: Row) {
      rows.set(v.key, JSON.parse(JSON.stringify(v)))
      return {}
    },
    delete(k: string) {
      rows.delete(k)
      return {}
    },
    getAll() {
      const req: { onsuccess?: () => void; onerror?: () => void; result?: unknown; error?: unknown } = {}
      if (failGetAll) {
        req.error = new Error('indexeddb read failed')
        queueMicrotask(() => req.onerror?.())
        return req
      }
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

const MATCH = 30
const rally = (setId: number, rallyNum: number) => ({
  matchId: MATCH,
  setId,
  rallyNum,
  payload: { rally_num: rallyNum },
  queued_at: `2026-10-20T00:00:0${rallyNum}Z`,
})

describe('G4 #529 ログアウト時の未送信ラリー', () => {
  beforeEach(() => {
    installFakeIndexedDb()
  })

  it('読み取り失敗時は 0 ではなく例外を投げる (0 件と混同しない)', async () => {
    failGetAll = true
    await expect(countPendingForUserStrict(5)).rejects.toThrow()
  })

  it('本人の未送信件数を数える (他人と所有者不明は除く)', async () => {
    await stashRallyBeforeSave(5, rally(1, 1))
    await stashRallyBeforeSave(5, rally(1, 2))
    await stashRallyBeforeSave(9, rally(1, 3)) // 別ユーザー
    await stashRallyBeforeSave(null, rally(1, 4)) // 所有者不明
    expect(await countPendingForUserStrict(5)).toBe(2)
    expect(await countPendingForUserStrict(9)).toBe(1)
  })

  it('send 失敗時は reject し、データを残す (ログアウトしない前提)', async () => {
    await stashRallyBeforeSave(5, rally(1, 1))
    await stashRallyBeforeSave(5, rally(1, 2))
    const post = vi.fn().mockResolvedValue({ success: false })
    await expect(flushPendingForUser(5, post)).rejects.toThrow()
    // 1 件目で失敗して止まり、データは残る
    expect(await countPendingForUserStrict(5)).toBe(2)
  })

  it('send 成功時は全件送ってキューから消す', async () => {
    await stashRallyBeforeSave(5, rally(1, 1))
    await stashRallyBeforeSave(5, rally(1, 2))
    const post = vi.fn().mockResolvedValue({ success: true })
    await flushPendingForUser(5, post)
    expect(post).toHaveBeenCalledTimes(2)
    expect(await countPendingForUserStrict(5)).toBe(0)
  })

  it('delete は本人の行だけ消し、他人・所有者不明は残す', async () => {
    await stashRallyBeforeSave(5, rally(1, 1))
    await stashRallyBeforeSave(9, rally(1, 2)) // 別ユーザー
    await stashRallyBeforeSave(null, rally(1, 3)) // 所有者不明
    expect(await deletePendingForUser(5)).toBe(1)
    expect(await countPendingForUserStrict(5)).toBe(0)
    // 別ユーザーの行は残る
    expect(await countPendingForUserStrict(9)).toBe(1)
    // 所有者不明の行も残る (unowned/ キー)
    const unowned = [...rows.values()].filter((r) => String(r.key).startsWith('unowned/'))
    expect(unowned).toHaveLength(1)
  })
})
