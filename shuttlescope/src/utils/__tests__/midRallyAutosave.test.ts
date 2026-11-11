/**
 * mid-rally autosave の単体テスト。
 *
 * 依頼の代わり (setTimer/clearTimer/post/stash/remove) を全て注入して、
 * 実時間タイマーを使わずに挙動を検証する:
 *   (1) 入力から 5 秒後 (debounceMs=5000) に送信が 1 回呼ばれ、replace_strokes=true / final=false。
 *   (3) 送信が失敗したら端末の退避 (stashRallyBeforeSave) を消さず (removeRallyAfterSave 未呼出)、
 *       30 秒後 (retryMs=30000) の再試行がスケジュールされる。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

import * as offlineQueue from '@/utils/offlineStrokeQueue'
import { MidRallyAutosaver, type MidRallySnapshot } from '@/utils/midRallyAutosave'
import type { StrokeInput } from '@/types'

function makeSnapshot(): MidRallySnapshot {
  const strokes: StrokeInput[] = [
    { stroke_num: 1, player: 'player_a', shot_type: 'clear', is_backhand: false, is_around_head: false },
  ]
  return {
    matchId: 7,
    payloadArgs: {
      setId: 3,
      rallyNum: 11,
      winner: 'player_a',
      endType: 'in_progress',
      strokes,
      scoreAAfter: 5,
      scoreBAfter: 4,
      rallyStartTimestamp: 1.5,
      isBasicMode: true,
    },
  }
}

/** 注入タイマー: スケジュールされた (fn, ms) を捕まえ、手動で発火できる。 */
function makeTimerHarness() {
  const scheduled: Array<{ id: number; fn: () => void; ms: number }> = []
  let nextId = 1
  const setTimer = (fn: () => void, ms: number) => {
    const id = nextId++
    scheduled.push({ id, fn, ms })
    return id as unknown as ReturnType<typeof setTimeout>
  }
  const clearTimer = (id: ReturnType<typeof setTimeout>) => {
    const idx = scheduled.findIndex((s) => s.id === (id as unknown as number))
    if (idx >= 0) scheduled.splice(idx, 1)
  }
  // 最後にスケジュールされた (生きている) タイマーを発火する。
  const fireLast = async () => {
    const last = scheduled[scheduled.length - 1]
    expect(last).toBeTruthy()
    // 発火したタイマーはキューから外す (setTimeout 相当)。
    scheduled.splice(scheduled.indexOf(last), 1)
    last.fn()
    // flush 内の await を消化。
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()
  }
  return { scheduled, setTimer, clearTimer, fireLast }
}

describe('MidRallyAutosaver', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('(1) 入力から 5 秒後に replace_strokes=true / final=false で送信する', async () => {
    const timers = makeTimerHarness()
    const stashSpy = vi.spyOn(offlineQueue, 'stashMidRally').mockResolvedValue(true)
    const removeSpy = vi.spyOn(offlineQueue, 'removeMidRally').mockResolvedValue()
    const post = vi.fn().mockResolvedValue({ success: true })
    const onSent = vi.fn()

    const saver = new MidRallyAutosaver({
      getSnapshot: makeSnapshot,
      getOwnerUserId: () => 42,
      post,
      onSent,
      setTimer: timers.setTimer,
      clearTimer: timers.clearTimer,
    })

    saver.notifyInput()
    // 入力直後はまだ送らない。スケジュールは 5000ms。
    expect(post).not.toHaveBeenCalled()
    expect(timers.scheduled[timers.scheduled.length - 1].ms).toBe(5000)

    await timers.fireLast()

    expect(stashSpy).toHaveBeenCalledTimes(1)
    expect(post).toHaveBeenCalledTimes(1)
    const [path, body, headers] = post.mock.calls[0]
    expect(path).toBe('/strokes/batch')
    expect((body as { replace_strokes?: boolean }).replace_strokes).toBe(true)
    expect((body as { final?: boolean }).final).toBe(false)
    // mid-rally は確定とは別の冪等キー (offline-mid-...) を必ず付ける。
    // これが確定ラリーの冪等キー (offline-...) を先取りしないことを保証する。
    expect((headers as Record<string, string>)['X-Idempotency-Key']).toBe('offline-mid-42-7-3-11')
    expect((headers as Record<string, string>)['X-Idempotency-Key']).not.toBe('offline-42-7-3-11')
    expect(removeSpy).toHaveBeenCalledTimes(1)
    expect(onSent).toHaveBeenCalledTimes(1)
  })

  it('連続入力は最後の入力から 5 秒後に 1 回だけ送る (デバウンス)', async () => {
    const timers = makeTimerHarness()
    vi.spyOn(offlineQueue, 'stashMidRally').mockResolvedValue(true)
    vi.spyOn(offlineQueue, 'removeMidRally').mockResolvedValue()
    const post = vi.fn().mockResolvedValue({ success: true })

    const saver = new MidRallyAutosaver({
      getSnapshot: makeSnapshot,
      getOwnerUserId: () => 42,
      post,
      setTimer: timers.setTimer,
      clearTimer: timers.clearTimer,
    })

    saver.notifyInput()
    saver.notifyInput()
    saver.notifyInput()
    // 前のタイマーは clearTimer され、生きているのは 1 つだけ。
    expect(timers.scheduled.length).toBe(1)

    await timers.fireLast()
    expect(post).toHaveBeenCalledTimes(1)
  })

  it('(3) 送信失敗時は退避を消さず、30 秒後の再試行をスケジュールする', async () => {
    const timers = makeTimerHarness()
    const stashSpy = vi.spyOn(offlineQueue, 'stashMidRally').mockResolvedValue(true)
    const removeSpy = vi.spyOn(offlineQueue, 'removeMidRally').mockResolvedValue()
    const post = vi.fn().mockRejectedValue(new Error('network down'))
    const onError = vi.fn()

    const saver = new MidRallyAutosaver({
      getSnapshot: makeSnapshot,
      getOwnerUserId: () => 42,
      post,
      onError,
      setTimer: timers.setTimer,
      clearTimer: timers.clearTimer,
    })

    saver.notifyInput()
    await timers.fireLast()

    // 退避は残す: stash は呼ばれ、remove は呼ばれない。
    expect(stashSpy).toHaveBeenCalledTimes(1)
    expect(removeSpy).not.toHaveBeenCalled()
    expect(onError).toHaveBeenCalledTimes(1)
    // 再試行が 30000ms でスケジュールされている。
    expect(timers.scheduled.length).toBe(1)
    expect(timers.scheduled[timers.scheduled.length - 1].ms).toBe(30000)
  })

  it('送るストロークが無ければ何もしない', async () => {
    const timers = makeTimerHarness()
    const stashSpy = vi.spyOn(offlineQueue, 'stashMidRally').mockResolvedValue(true)
    const post = vi.fn().mockResolvedValue({ success: true })

    const saver = new MidRallyAutosaver({
      getSnapshot: () => {
        const snap = makeSnapshot()
        snap.payloadArgs.strokes = []
        return snap
      },
      getOwnerUserId: () => 42,
      post,
      setTimer: timers.setTimer,
      clearTimer: timers.clearTimer,
    })

    saver.notifyInput()
    await timers.fireLast()
    expect(stashSpy).not.toHaveBeenCalled()
    expect(post).not.toHaveBeenCalled()
  })
})
