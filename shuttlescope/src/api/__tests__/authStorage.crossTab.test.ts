import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// fix/auth-session-persist: 認証情報を localStorage に置いて同一ブラウザの全タブで
// 共有し、refresh を 1 本に束ね、ログアウトを全タブへ伝える authStorage の挙動を検証する。
// jsdom は 1 つの window だが、別タブからの書き込みは StorageEvent を dispatch して
// 模擬する (本番では別タブの localStorage 書き込みがこのタブに storage イベントで届く)。

describe('authStorage cross-tab sharing', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    vi.resetModules()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
    localStorage.clear()
    sessionStorage.clear()
  })

  it('writes auth values to localStorage so another tab can read them', async () => {
    const { setAuthItem, getAuthItem, TOKEN_KEY } = await import('@/api/authStorage')
    setAuthItem(TOKEN_KEY, 'access-shared')
    // localStorage が主ストレージ (他タブと共有される)。
    expect(localStorage.getItem(TOKEN_KEY)).toBe('access-shared')
    // sessionStorage にも互換ミラーされる (旧テスト・旧タブ互換)。
    expect(sessionStorage.getItem(TOKEN_KEY)).toBe('access-shared')
    // 読みは localStorage 優先。
    expect(getAuthItem(TOKEN_KEY)).toBe('access-shared')
  })

  it('reads from localStorage first, falling back to sessionStorage', async () => {
    const { getAuthItem, REFRESH_KEY } = await import('@/api/authStorage')
    // 旧タブ由来の sessionStorage のみの値もフォールバックで読める。
    sessionStorage.setItem(REFRESH_KEY, 'refresh-session-only')
    expect(getAuthItem(REFRESH_KEY)).toBe('refresh-session-only')
    // localStorage に値があればそちらが優先される。
    localStorage.setItem(REFRESH_KEY, 'refresh-local')
    expect(getAuthItem(REFRESH_KEY)).toBe('refresh-local')
  })

  it('migrates existing sessionStorage auth values into localStorage on first load', async () => {
    sessionStorage.setItem('shuttlescope_token', 'migrate-access')
    sessionStorage.setItem('shuttlescope_refresh_token', 'migrate-refresh')
    sessionStorage.setItem('shuttlescope_role', 'annotator')
    const { migrateSessionToLocal } = await import('@/api/authStorage')
    migrateSessionToLocal()
    expect(localStorage.getItem('shuttlescope_token')).toBe('migrate-access')
    expect(localStorage.getItem('shuttlescope_refresh_token')).toBe('migrate-refresh')
    expect(localStorage.getItem('shuttlescope_role')).toBe('annotator')
  })

  it('does not overwrite a newer localStorage value during migration', async () => {
    // 他タブが既に新しい値を localStorage に書いている状況。
    localStorage.setItem('shuttlescope_token', 'newer-from-other-tab')
    sessionStorage.setItem('shuttlescope_token', 'older-session')
    const { migrateSessionToLocal } = await import('@/api/authStorage')
    migrateSessionToLocal()
    expect(localStorage.getItem('shuttlescope_token')).toBe('newer-from-other-tab')
  })

  it('re-dispatches AUTH_CHANGED_EVENT when another tab changes an auth key', async () => {
    const { installCrossTabAuthSync, AUTH_CHANGED_EVENT, TOKEN_KEY } = await import('@/api/authStorage')
    installCrossTabAuthSync()
    const onChange = vi.fn()
    window.addEventListener(AUTH_CHANGED_EVENT, onChange)
    try {
      // 別タブが token を書き換えた = storage イベントが届く、を模擬する。
      window.dispatchEvent(new StorageEvent('storage', { key: TOKEN_KEY, newValue: 'from-other-tab' }))
      // このタブ発の 1 発に対して少なくとも 1 回は再 dispatch される。
      expect(onChange).toHaveBeenCalled()
    } finally {
      window.removeEventListener(AUTH_CHANGED_EVENT, onChange)
    }
  })

  it('ignores storage events for unrelated keys', async () => {
    const { installCrossTabAuthSync, AUTH_CHANGED_EVENT } = await import('@/api/authStorage')
    installCrossTabAuthSync()
    const onChange = vi.fn()
    window.addEventListener(AUTH_CHANGED_EVENT, onChange)
    try {
      window.dispatchEvent(new StorageEvent('storage', { key: 'some_unrelated_key', newValue: 'x' }))
      expect(onChange).not.toHaveBeenCalled()
    } finally {
      window.removeEventListener(AUTH_CHANGED_EVENT, onChange)
    }
  })

  it('propagates logout to other tabs (clearing the token fires AUTH_CHANGED_EVENT)', async () => {
    const { installCrossTabAuthSync, AUTH_CHANGED_EVENT, TOKEN_KEY } = await import('@/api/authStorage')
    installCrossTabAuthSync()
    const onChange = vi.fn()
    window.addEventListener(AUTH_CHANGED_EVENT, onChange)
    try {
      // 他タブでログアウト = token が localStorage から消える (newValue=null)。
      window.dispatchEvent(new StorageEvent('storage', { key: TOKEN_KEY, newValue: null }))
      // ログアウトがこのタブに伝わり、再同期イベントが発火する。
      expect(onChange).toHaveBeenCalled()
    } finally {
      window.removeEventListener(AUTH_CHANGED_EVENT, onChange)
    }
  })

  it('installCrossTabAuthSync does not register the storage listener twice', async () => {
    const addSpy = vi.spyOn(window, 'addEventListener')
    const { installCrossTabAuthSync } = await import('@/api/authStorage')
    installCrossTabAuthSync()
    installCrossTabAuthSync()
    const storageRegistrations = addSpy.mock.calls.filter(([type]) => type === 'storage')
    expect(storageRegistrations.length).toBe(1)
    addSpy.mockRestore()
  })
})

describe('authStorage refresh single-flight lock', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('serializes refresh through navigator.locks when available', async () => {
    // 本物の LockManager と同じく「同名ロックは 1 本ずつ直列化する」モックを作り、
    // withRefreshLock がその単一ロックに全呼び出しを束ねることを確認する。
    let active = 0
    let maxActive = 0
    const requested: string[] = []
    const chains: Record<string, Promise<unknown>> = {}
    const locksMock = {
      request: (name: string, cb: () => Promise<unknown>) => {
        requested.push(name)
        // 同名ロックを直列化する: 直前の request が解放されるまで待ってから cb を走らせる。
        const prev = chains[name] ?? Promise.resolve()
        const run = prev.then(async () => {
          active += 1
          maxActive = Math.max(maxActive, active)
          try {
            return await cb()
          } finally {
            active -= 1
          }
        })
        // 次の request が待てるよう、失敗しても鎖が切れないチェーンを保持する。
        chains[name] = run.then(
          () => undefined,
          () => undefined,
        )
        return run
      },
    }
    vi.stubGlobal('navigator', { locks: locksMock } as unknown as Navigator)

    const { withRefreshLock } = await import('@/api/authStorage')
    const run = () =>
      withRefreshLock(async () => {
        await new Promise((r) => setTimeout(r, 5))
        return 'done'
      })
    const results = await Promise.all([run(), run(), run()])

    expect(results).toEqual(['done', 'done', 'done'])
    // すべて同じ名前付きロックを要求している (全タブで 1 本に束ねる鍵)。
    expect(new Set(requested)).toEqual(new Set(['shuttlescope-refresh']))
    // 単一ロックに束ねられ、同時実行は 1 本に抑えられる。
    expect(maxActive).toBe(1)
  })

  it('runs the function without a lock when navigator.locks is unavailable', async () => {
    vi.stubGlobal('navigator', {} as unknown as Navigator)
    const { withRefreshLock } = await import('@/api/authStorage')
    const out = await withRefreshLock(async () => 'no-lock-ok')
    expect(out).toBe('no-lock-ok')
  })

  it('falls back to running the function if the lock mechanism itself throws', async () => {
    const locksMock = {
      request: async () => {
        throw new Error('locks backend unavailable')
      },
    }
    vi.stubGlobal('navigator', { locks: locksMock } as unknown as Navigator)
    const { withRefreshLock } = await import('@/api/authStorage')
    const out = await withRefreshLock(async () => 'ran-anyway')
    expect(out).toBe('ran-anyway')
  })
})
