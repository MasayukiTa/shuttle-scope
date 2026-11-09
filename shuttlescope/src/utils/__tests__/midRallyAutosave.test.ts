/**
 * ミッドラリー自動保存 (MidRallyAutosaver) のテスト。
 *
 * 確認すること:
 *   1. 最後の入力から 5 秒後に 1 回だけ送る (連続入力はデバウンスを張り直す)。
 *   2. ミッドラリー保存と「ラリー終了時の最終保存」が **同じ安定冪等キー** を使う。
 *      => サーバーの /strokes/batch は同一 (set,rally)+同一キーを replay / already_saved
 *         とするため strokes は二重 INSERT されず、部分一意制約
 *         uq_strokes_rally_id_stroke_num_active (deleted_at IS NULL) に当たらない。
 *   3. 送信に失敗したら PR 250 の退避 (stashRallyBeforeSave) を消さず、30 秒後の
 *      再試行、または次の入力で送り直す。成功した分だけ未保存から外す。
 *
 * offlineStrokeQueue が使う IndexedDB は、既存テスト (unownedRallyStash.test.ts)
 * と同じ最小スタブで差し替える。fake-indexeddb は依存に無い。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  MidRallyAutosaver,
  MID_RALLY_DEBOUNCE_MS,
  MID_RALLY_RETRY_MS,
  isTransientFailure,
  type MidRallySnapshot,
} from '../midRallyAutosave'
import {
  listPendingForMatch,
  offlineStrokeIdempotencyKey,
} from '../offlineStrokeQueue'
import type { StrokeInput } from '@/types'

// ─── IndexedDB スタブ (unownedRallyStash.test.ts と同型) ──────────────────────
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

// ─── fixtures ────────────────────────────────────────────────────────────────
const OWNER = 5
const MATCH = 22
const SET = 3
const RALLY = 7

const stroke = (n: number): StrokeInput => ({
  stroke_num: n,
  player: n % 2 === 1 ? 'player_a' : 'player_b',
  shot_type: 'clear',
  is_backhand: false,
  is_around_head: false,
})

const snap = (strokeCount: number, owner: number | null = OWNER): MidRallySnapshot => ({
  ownerUserId: owner,
  matchId: MATCH,
  setId: SET,
  rallyNum: RALLY,
  strokes: Array.from({ length: strokeCount }, (_, i) => stroke(i + 1)),
  winner: 'player_a',
  endType: 'winner',
  scoreAAfter: 5,
  scoreBAfter: 3,
  rallyStartTimestamp: 100,
  isBasicMode: true,
})

/** マイクロタスクを吐き切る (IndexedDB スタブの queueMicrotask を解決する)。 */
async function drain(): Promise<void> {
  // IndexedDB スタブの queueMicrotask は 2 段ネスト (transaction.oncomplete)。
  // 連続 2 回 flush するテストでは 1 回目の post→removeRallyAfterSave まで
  // 完全に吐き切ってから 2 回目に進む必要があるため、十分な回数回す。
  for (let i = 0; i < 40; i++) await Promise.resolve()
}

beforeEach(() => {
  installFakeIndexedDb()
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('MidRallyAutosaver デバウンス', () => {
  it('最後の入力から 5 秒後に 1 回だけ送る (連続入力は張り直し)', async () => {
    const post = vi.fn().mockResolvedValue({ success: true, data: { rally_id: 999 } })
    const s = new MidRallyAutosaver({ post })

    s.onStroke(snap(1))
    vi.advanceTimersByTime(MID_RALLY_DEBOUNCE_MS - 1)
    s.onStroke(snap(2)) // 入力が続いたのでタイマー張り直し
    vi.advanceTimersByTime(MID_RALLY_DEBOUNCE_MS - 1)
    expect(post).not.toHaveBeenCalled() // まだ 5 秒経っていない

    vi.advanceTimersByTime(1) // 最後の入力から 5 秒
    await drain()
    expect(post).toHaveBeenCalledTimes(1)
    const [path, payload] = post.mock.calls[0]
    expect(path).toBe('/strokes/batch')
    // 最後のスナップショット (2 打) が送られる
    expect((payload as { strokes: unknown[] }).strokes).toHaveLength(2)
  })

  it('5 秒未満では送らない', async () => {
    const post = vi.fn().mockResolvedValue({ success: true })
    const s = new MidRallyAutosaver({ post })
    s.onStroke(snap(1))
    vi.advanceTimersByTime(MID_RALLY_DEBOUNCE_MS - 1)
    await drain()
    expect(post).not.toHaveBeenCalled()
  })

  it('打球 0 のラリーは送らない', async () => {
    const post = vi.fn().mockResolvedValue({ success: true })
    const s = new MidRallyAutosaver({ post })
    s.onStroke(snap(0))
    vi.advanceTimersByTime(MID_RALLY_DEBOUNCE_MS)
    await drain()
    expect(post).not.toHaveBeenCalled()
  })

  it('cancel で保留中の送信を止める (ラリー確定時)', async () => {
    const post = vi.fn().mockResolvedValue({ success: true })
    const s = new MidRallyAutosaver({ post })
    s.onStroke(snap(1))
    s.cancel()
    vi.advanceTimersByTime(MID_RALLY_DEBOUNCE_MS * 2)
    await drain()
    expect(post).not.toHaveBeenCalled()
    expect(s.hasPending()).toBe(false)
  })
})

describe('二重保存にならない (終了時最終保存と同じ安定冪等キー)', () => {
  it('ミッドラリー保存は終了時の最終保存と同一の X-Idempotency-Key を送る', async () => {
    const post = vi.fn().mockResolvedValue({ success: true, data: { rally_id: 999 } })
    const s = new MidRallyAutosaver({ post })
    s.onStroke(snap(3))
    vi.advanceTimersByTime(MID_RALLY_DEBOUNCE_MS)
    await drain()

    const headers = post.mock.calls[0][2] as Record<string, string>
    // 既存の確定保存 (AnnotatorPage/LiveInputPage) と **同じ** キー生成関数。
    const expectedKey = offlineStrokeIdempotencyKey(OWNER, MATCH, SET, RALLY)
    expect(headers['X-Idempotency-Key']).toBe(expectedKey)
    // キーは (owner, match, set, rally) だけで決まり、打球数や時刻に依らない
    // => 何打目で送っても、終了時に送っても同じ => サーバーは replay / already_saved
    //    とし、uq_strokes_rally_id_stroke_num_active に当たる二重 INSERT を起こさない。
    expect(expectedKey).toBe(`offline-${OWNER}-${MATCH}-${SET}-${RALLY}`)
  })

  it('同じラリーを複数回フラッシュしてもキーは不変 (何度送っても二重にならない)', async () => {
    const post = vi.fn().mockResolvedValue({ success: true, data: { rally_id: 999 } })
    const s = new MidRallyAutosaver({ post })

    s.onStroke(snap(2))
    vi.advanceTimersByTime(MID_RALLY_DEBOUNCE_MS)
    await drain()

    s.onStroke(snap(4)) // さらに打って再度デバウンス
    vi.advanceTimersByTime(MID_RALLY_DEBOUNCE_MS)
    await drain()

    expect(post).toHaveBeenCalledTimes(2)
    const key0 = (post.mock.calls[0][2] as Record<string, string>)['X-Idempotency-Key']
    const key1 = (post.mock.calls[1][2] as Record<string, string>)['X-Idempotency-Key']
    expect(key0).toBe(key1)
  })

  it('owner 不明ならキー無しで送る (サーバーの set/rally 既存チェックに委ねる)', async () => {
    const post = vi.fn().mockResolvedValue({ success: true })
    const s = new MidRallyAutosaver({ post })
    s.onStroke(snap(2, null))
    vi.advanceTimersByTime(MID_RALLY_DEBOUNCE_MS)
    await drain()
    expect(post).toHaveBeenCalledTimes(1)
    expect(post.mock.calls[0][2]).toBeUndefined()
  })
})

describe('退避と再試行', () => {
  it('送信前に退避し、成功したら未保存から外す', async () => {
    const post = vi.fn().mockResolvedValue({ success: true, data: { rally_id: 999 } })
    const s = new MidRallyAutosaver({ post })
    s.onStroke(snap(2))
    vi.advanceTimersByTime(MID_RALLY_DEBOUNCE_MS)
    await drain()
    // 成功後は本人の未保存キューに残っていない
    const pending = await listPendingForMatch(MATCH, OWNER)
    expect(pending).toEqual([])
  })

  it('失敗したら退避を消さず、30 秒後に再試行し、成功で未保存から外す', async () => {
    const err = Object.assign(new Error('network'), { status: undefined })
    const post = vi
      .fn()
      .mockRejectedValueOnce(err) // 1 回目: 失敗
      .mockResolvedValueOnce({ success: true, data: { rally_id: 999 } }) // 再試行: 成功
    const s = new MidRallyAutosaver({ post })

    s.onStroke(snap(2))
    vi.advanceTimersByTime(MID_RALLY_DEBOUNCE_MS)
    await drain()
    expect(post).toHaveBeenCalledTimes(1)
    // 失敗後、退避は残っている
    expect(await listPendingForMatch(MATCH, OWNER)).toHaveLength(1)
    expect(s.hasPending()).toBe(true) // 再試行タイマーが張られている

    // 30 秒後に再試行
    vi.advanceTimersByTime(MID_RALLY_RETRY_MS)
    await drain()
    expect(post).toHaveBeenCalledTimes(2)
    // 再試行成功で未保存から外れる
    expect(await listPendingForMatch(MATCH, OWNER)).toEqual([])
  })

  it('失敗後、次の入力 (5 秒デバウンス) でも送り直す', async () => {
    const err = Object.assign(new Error('timeout'), { status: 408 })
    const post = vi
      .fn()
      .mockRejectedValueOnce(err)
      .mockResolvedValueOnce({ success: true })
    const s = new MidRallyAutosaver({ post })

    s.onStroke(snap(2))
    vi.advanceTimersByTime(MID_RALLY_DEBOUNCE_MS)
    await drain()
    expect(post).toHaveBeenCalledTimes(1)

    // 次の入力で再度デバウンス -> 送信
    s.onStroke(snap(3))
    vi.advanceTimersByTime(MID_RALLY_DEBOUNCE_MS)
    await drain()
    expect(post).toHaveBeenCalledTimes(2)
    expect(await listPendingForMatch(MATCH, OWNER)).toEqual([])
  })

  it('success=false は一過性扱いで退避を残し再試行する', async () => {
    const post = vi
      .fn()
      .mockResolvedValueOnce({ success: false })
      .mockResolvedValueOnce({ success: true })
    const s = new MidRallyAutosaver({ post })
    s.onStroke(snap(2))
    vi.advanceTimersByTime(MID_RALLY_DEBOUNCE_MS)
    await drain()
    expect(await listPendingForMatch(MATCH, OWNER)).toHaveLength(1)
    expect(s.hasPending()).toBe(true)
    vi.advanceTimersByTime(MID_RALLY_RETRY_MS)
    await drain()
    expect(await listPendingForMatch(MATCH, OWNER)).toEqual([])
  })
})

describe('isTransientFailure', () => {
  it('ネットワーク断・タイムアウト (status 無し) は一過性', () => {
    expect(isTransientFailure(new Error('x'))).toBe(true)
    expect(isTransientFailure(null)).toBe(true)
  })
  it('5xx は一過性、恒久 4xx は非一過性、408/429 は一過性', () => {
    expect(isTransientFailure({ status: 503 })).toBe(true)
    expect(isTransientFailure({ status: 500 })).toBe(true)
    expect(isTransientFailure({ status: 408 })).toBe(true)
    expect(isTransientFailure({ status: 429 })).toBe(true)
    expect(isTransientFailure({ status: 400 })).toBe(false)
    expect(isTransientFailure({ status: 422 })).toBe(false)
  })
})

describe('恒久的失敗では再試行タイマーを張らない (退避は消さない)', () => {
  it('422 は退避を残すが 30 秒再試行はしない', async () => {
    const err = Object.assign(new Error('bad'), { status: 422 })
    const post = vi.fn().mockRejectedValue(err)
    const s = new MidRallyAutosaver({ post })
    s.onStroke(snap(2))
    vi.advanceTimersByTime(MID_RALLY_DEBOUNCE_MS)
    await drain()
    // 退避は残る (確定時の最終保存 / useOfflineSync に委ねる)
    expect(await listPendingForMatch(MATCH, OWNER)).toHaveLength(1)
    // 恒久的なので再試行タイマーは張らない
    expect(s.hasPending()).toBe(false)
    vi.advanceTimersByTime(MID_RALLY_RETRY_MS * 2)
    await drain()
    expect(post).toHaveBeenCalledTimes(1) // 再送されていない
  })
})
