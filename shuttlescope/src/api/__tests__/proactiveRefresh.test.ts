import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { startProactiveRefresh, REFRESH_SKEW_MS } from '@/api/proactiveRefresh'
import { TOKEN_KEY } from '@/api/authStorage'

// base64url でエンコードした、exp を持つダミー JWT を作る。署名は検証しないので適当でよい。
function makeToken(expEpochSec: number): string {
  const header = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '')
  const payload = btoa(JSON.stringify({ sub: 1, exp: expEpochSec }))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '')
  return `${header}.${payload}.sig`
}

describe('proactive refresh scheduler (方針C)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('fires a proactive refresh 2 minutes before the access token expires', () => {
    const nowMs = 1_000_000_000_000
    const expMs = nowMs + 15 * 60_000 // 15 分後に失効
    const token = makeToken(Math.floor(expMs / 1000))

    const refresh = vi.fn().mockResolvedValue('ok')
    const timers: Array<{ cb: () => void; at: number }> = []
    let clock = nowMs

    const handle = startProactiveRefresh({
      getToken: () => token,
      refresh,
      now: () => clock,
      setTimer: (cb, ms) => {
        timers.push({ cb, at: clock + ms })
        return timers.length - 1
      },
      clearTimer: () => {},
      addVisibilityListener: () => () => {},
      isHidden: () => false,
    })

    // 1 本だけ予約され、発火予定は exp の REFRESH_SKEW_MS (=2 分) 前。
    expect(timers).toHaveLength(1)
    expect(timers[0].at).toBe(expMs - REFRESH_SKEW_MS)

    // まだ 2 分前に達していなければ発火しない。
    expect(refresh).not.toHaveBeenCalled()

    // 2 分前の時刻に進めてタイマーを発火させる。
    clock = expMs - REFRESH_SKEW_MS
    timers[0].cb()
    expect(refresh).toHaveBeenCalledTimes(1)

    handle.stop()
  })

  it('fires a proactive refresh when the tab becomes visible again within the skew window', () => {
    const nowMs = 1_000_000_000_000
    // 残り 1 分 (skew=2 分 未満) で失効するトークン。表示復帰で即 refresh すべき。
    const expMs = nowMs + 60_000
    const token = makeToken(Math.floor(expMs / 1000))

    const refresh = vi.fn().mockResolvedValue('ok')
    let visibilityCb: (() => void) | null = null
    let hidden = true

    const handle = startProactiveRefresh({
      getToken: () => token,
      refresh,
      now: () => nowMs,
      setTimer: () => 0,
      clearTimer: () => {},
      addVisibilityListener: (cb) => {
        visibilityCb = cb
        return () => {}
      },
      isHidden: () => hidden,
    })

    // タブは非表示。まだ refresh は走らない。
    expect(refresh).not.toHaveBeenCalled()

    // タブが表示に戻る。残りが skew を切っているので即 refresh。
    hidden = false
    expect(visibilityCb).not.toBeNull()
    visibilityCb!()
    expect(refresh).toHaveBeenCalledTimes(1)

    handle.stop()
  })

  it('does not refresh on visibility when plenty of time remains', () => {
    const nowMs = 1_000_000_000_000
    const expMs = nowMs + 15 * 60_000 // 残り 15 分。skew より十分長い。
    const token = makeToken(Math.floor(expMs / 1000))

    const refresh = vi.fn().mockResolvedValue('ok')
    let visibilityCb: (() => void) | null = null

    const handle = startProactiveRefresh({
      getToken: () => token,
      refresh,
      now: () => nowMs,
      setTimer: () => 0,
      clearTimer: () => {},
      addVisibilityListener: (cb) => {
        visibilityCb = cb
        return () => {}
      },
      isHidden: () => false,
    })

    visibilityCb!()
    expect(refresh).not.toHaveBeenCalled()

    handle.stop()
  })

  it('reads the token from localStorage (authStorage) and schedules a refresh 2 minutes before expiry', () => {
    const nowMs = 1_000_000_000_000
    const expMs = nowMs + 15 * 60_000 // 15 分後に失効
    const token = makeToken(Math.floor(expMs / 1000))
    // PR 258 以降、認証の保存先は localStorage。getToken を渡さず実 readToken (=getAuthItem) 経由で読めることを確かめる。
    localStorage.clear()
    sessionStorage.clear()
    localStorage.setItem(TOKEN_KEY, token)

    const refresh = vi.fn().mockResolvedValue('ok')
    const timers: Array<{ cb: () => void; at: number }> = []
    let clock = nowMs

    const handle = startProactiveRefresh({
      // getToken は渡さない — 本番の readToken が localStorage を読むことを検証する。
      refresh,
      now: () => clock,
      setTimer: (cb, ms) => {
        timers.push({ cb, at: clock + ms })
        return timers.length - 1
      },
      clearTimer: () => {},
      addVisibilityListener: () => () => {},
      isHidden: () => false,
    })

    // localStorage のトークンを読んで 1 本予約し、発火予定は exp の 2 分前。
    expect(timers).toHaveLength(1)
    expect(timers[0].at).toBe(expMs - REFRESH_SKEW_MS)
    expect(refresh).not.toHaveBeenCalled()

    // 失効の 2 分前に進めてタイマーを発火させる。
    clock = expMs - REFRESH_SKEW_MS
    timers[0].cb()
    expect(refresh).toHaveBeenCalledTimes(1)

    handle.stop()
    localStorage.clear()
  })
})
