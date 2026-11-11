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

  it('writes auth values to localStorage only (no sessionStorage mirror) when localStorage works', async () => {
    const { setAuthItem, getAuthItem, TOKEN_KEY } = await import('@/api/authStorage')
    setAuthItem(TOKEN_KEY, 'access-shared')
    // localStorage が主ストレージ (他タブと共有される)。
    expect(localStorage.getItem(TOKEN_KEY)).toBe('access-shared')
    // localStorage が使えるので sessionStorage には書かない (タブ固有のミラーを残さない)。
    // ミラーを残すと他タブでのログアウト後もそのタブに値が残り、cross-tab logout が不成立になる。
    expect(sessionStorage.getItem(TOKEN_KEY)).toBeNull()
    expect(getAuthItem(TOKEN_KEY)).toBe('access-shared')
  })

  it('reads from localStorage only when localStorage works (does not fall back to sessionStorage)', async () => {
    const { getAuthItem, REFRESH_KEY } = await import('@/api/authStorage')
    // localStorage が使える環境では、sessionStorage にしか無い値は読まない。
    // (他タブのログアウトで localStorage が空になったとき、残った sessionStorage を拾わない。)
    sessionStorage.setItem(REFRESH_KEY, 'refresh-session-only')
    expect(getAuthItem(REFRESH_KEY)).toBeNull()
    // localStorage に値があればそれを読む。
    localStorage.setItem(REFRESH_KEY, 'refresh-local')
    expect(getAuthItem(REFRESH_KEY)).toBe('refresh-local')
  })

  it('uses sessionStorage as a fallback only when localStorage is unavailable', async () => {
    // localStorage を使用不可 (getItem/setItem が throw) に差し替え、sessionStorage 代替を検証する。
    const throwing = {
      getItem() { throw new Error('ls disabled') },
      setItem() { throw new Error('ls disabled') },
      removeItem() { throw new Error('ls disabled') },
      key() { return null },
      clear() {},
      length: 0,
    } as unknown as Storage
    vi.stubGlobal('localStorage', throwing)
    const { setAuthItem, getAuthItem, TOKEN_KEY } = await import('@/api/authStorage')
    setAuthItem(TOKEN_KEY, 'ls-off-value')
    // localStorage が使えないので sessionStorage に書かれ、そこから読める。
    expect(sessionStorage.getItem(TOKEN_KEY)).toBe('ls-off-value')
    expect(getAuthItem(TOKEN_KEY)).toBe('ls-off-value')
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
    // 移行後は sessionStorage の認証値を消す。タブ固有のミラーを残すと、
    // 他タブのログアウトが getAuthItem のフォールバックで無効化されなくなるため。
    expect(sessionStorage.getItem('shuttlescope_token')).toBeNull()
    expect(sessionStorage.getItem('shuttlescope_refresh_token')).toBeNull()
    expect(sessionStorage.getItem('shuttlescope_role')).toBeNull()
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

  // 2 タブ模擬 (本件の中心シナリオ): タブ A と B がログイン (localStorage 共有)。
  // タブ B がログアウトで localStorage の token を消す → タブ A に storage イベントが届く。
  // 期待: タブ A では getAuthItem(token) が null になり (= 未認証化)、残った sessionStorage の
  // ミラーを拾わない。さらに入力中ラリー退避のため AUTOSAVE_FLUSH_EVENT が発火する。
  it('cross-tab logout: other tab clearing the token logs this tab out and does not resurrect from sessionStorage', async () => {
    const { installCrossTabAuthSync, getAuthItem, TOKEN_KEY, REFRESH_KEY } = await import('@/api/authStorage')
    installCrossTabAuthSync()

    // タブ A がログイン済み: 本番では localStorage に入るが、ここでは「過去に sessionStorage の
    // ミラーが残ってしまっている」状況も併せて再現し、それを拾わないことを示す。
    localStorage.setItem(TOKEN_KEY, 'access-A')
    localStorage.setItem(REFRESH_KEY, 'refresh-A')
    sessionStorage.setItem(TOKEN_KEY, 'stale-mirror-A')
    sessionStorage.setItem(REFRESH_KEY, 'stale-mirror-refresh-A')

    const flush = vi.fn()
    window.addEventListener('shuttlescope:autosave-flush', flush)

    try {
      // タブ B がログアウト = localStorage から token が消える。タブ A に storage イベントが届く。
      localStorage.removeItem(TOKEN_KEY)
      window.dispatchEvent(new StorageEvent('storage', { key: TOKEN_KEY, newValue: null }))

      // 退避イベントが発火している (アノテータが開いていれば入力中ラリーを書き出す)。
      expect(flush).toHaveBeenCalled()
      // タブ A の sessionStorage ミラーは消され、getAuthItem は復活しない。
      expect(sessionStorage.getItem(TOKEN_KEY)).toBeNull()
      expect(sessionStorage.getItem(REFRESH_KEY)).toBeNull()
      expect(getAuthItem(TOKEN_KEY)).toBeNull()
    } finally {
      window.removeEventListener('shuttlescope:autosave-flush', flush)
    }
  })

  // 回帰 (customer request #1: タイムアウト・別タブのログアウト同期):
  // 無操作タイムアウト等でセッションが切れると、まず refresh token が localStorage から
  // 消える経路がある。そのとき別タブにも refresh token の消失が storage イベントで届く。
  // 期待: TOKEN_KEY のときと同じく、退避イベントが発火し、sessionStorage のミラーが消され、
  // getAuthItem がミラーから復活しない (authStorage.ts の e.key === REFRESH_KEY 分岐を保護する)。
  it('cross-tab logout via REFRESH_KEY: refresh token cleared in another tab logs this tab out and flushes', async () => {
    const { installCrossTabAuthSync, getAuthItem, TOKEN_KEY, REFRESH_KEY } = await import('@/api/authStorage')
    installCrossTabAuthSync()

    localStorage.setItem(TOKEN_KEY, 'access-A')
    localStorage.setItem(REFRESH_KEY, 'refresh-A')
    sessionStorage.setItem(TOKEN_KEY, 'stale-mirror-A')
    sessionStorage.setItem(REFRESH_KEY, 'stale-mirror-refresh-A')

    const flush = vi.fn()
    window.addEventListener('shuttlescope:autosave-flush', flush)

    try {
      // 別タブでセッション終了 = refresh token が localStorage から消える (newValue=null)。
      localStorage.removeItem(REFRESH_KEY)
      window.dispatchEvent(new StorageEvent('storage', { key: REFRESH_KEY, newValue: null }))

      // 退避イベントが発火している (入力中ラリーの書き出し)。
      expect(flush).toHaveBeenCalled()
      // sessionStorage のミラーは両キーとも消され、復活しない。
      expect(sessionStorage.getItem(TOKEN_KEY)).toBeNull()
      expect(sessionStorage.getItem(REFRESH_KEY)).toBeNull()
      expect(getAuthItem(REFRESH_KEY)).toBeNull()
    } finally {
      window.removeEventListener('shuttlescope:autosave-flush', flush)
    }
  })

  // 回帰 (customer request #1): ログアウトでない通常の refresh (token 更新) は storage イベントで
  // 届いても、入力中ラリーの退避 (autosave-flush) は起こさない。別タブのトークン更新で
  // 不要な flush を誘発しないことを守る (newValue != null は loggedOut 条件に該当しない)。
  it('cross-tab token refresh (non-null) does not trigger autosave-flush', async () => {
    const { installCrossTabAuthSync, TOKEN_KEY } = await import('@/api/authStorage')
    installCrossTabAuthSync()

    const flush = vi.fn()
    window.addEventListener('shuttlescope:autosave-flush', flush)

    try {
      // 別タブが token を新しい値に更新しただけ (ログアウトではない)。
      window.dispatchEvent(new StorageEvent('storage', { key: TOKEN_KEY, newValue: 'refreshed-access' }))
      expect(flush).not.toHaveBeenCalled()
    } finally {
      window.removeEventListener('shuttlescope:autosave-flush', flush)
    }
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
