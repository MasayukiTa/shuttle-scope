import { afterEach, beforeEach, describe, expect, it } from 'vitest'

// fix/auth-readers-app: PR #258 で認証の保存先が localStorage だけになったが、
// src/App.tsx に sessionStorage.getItem('shuttlescope_token') で直接読む箇所が
// 残り、ログイン後も空になっていた。該当箇所は authStorage の getAuthItem()
// に置き換えた。このテストは localStorage に認証値を入れた状態で、
// App.tsx が経由する getAuthItem(TOKEN_KEY 等) がその値を返すことを確かめる。

describe('App.tsx auth readers go through localStorage via getAuthItem', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
  })

  afterEach(() => {
    localStorage.clear()
    sessionStorage.clear()
  })

  it('getAuthItem returns the token stored in localStorage', async () => {
    const { getAuthItem, TOKEN_KEY } = await import('@/api/authStorage')
    localStorage.setItem(TOKEN_KEY, 'access-from-local')
    expect(getAuthItem(TOKEN_KEY)).toBe('access-from-local')
  })

  it('getAuthItem returns role and user id stored in localStorage', async () => {
    const { getAuthItem, ROLE_KEY, USER_ID_KEY } = await import('@/api/authStorage')
    localStorage.setItem(ROLE_KEY, 'coach')
    localStorage.setItem(USER_ID_KEY, 'u-42')
    expect(getAuthItem(ROLE_KEY)).toBe('coach')
    expect(getAuthItem(USER_ID_KEY)).toBe('u-42')
  })

  it('reads the localStorage token even when a stale sessionStorage value exists', async () => {
    const { getAuthItem, TOKEN_KEY } = await import('@/api/authStorage')
    // 旧ビルドが残した sessionStorage の値は拾わず、localStorage を読む。
    sessionStorage.setItem(TOKEN_KEY, 'stale-session')
    localStorage.setItem(TOKEN_KEY, 'access-from-local')
    expect(getAuthItem(TOKEN_KEY)).toBe('access-from-local')
  })
})
