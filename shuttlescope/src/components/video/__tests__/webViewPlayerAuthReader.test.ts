import { afterEach, beforeEach, describe, expect, it } from 'vitest'

// fix/auth-reader-webview: PR #258 で認証の保存先が localStorage だけになったが、
// src/components/video/WebViewPlayer.tsx は sessionStorage.getItem('shuttlescope_token')
// で直接読んでおり、ログイン後も常に空になっていた。該当箇所は authStorage の
// getAuthItem(TOKEN_KEY) に置き換えた。このテストは localStorage にトークンを入れた
// 状態で、WebViewPlayer が経由する getAuthItem(TOKEN_KEY) がその値を返すことを確かめる。

describe('WebViewPlayer auth reader goes through localStorage via getAuthItem', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
  })

  afterEach(() => {
    localStorage.clear()
    sessionStorage.clear()
  })

  it('getAuthItem(TOKEN_KEY) returns the token stored in localStorage', async () => {
    const { getAuthItem, TOKEN_KEY } = await import('@/api/authStorage')
    localStorage.setItem(TOKEN_KEY, 'webview-access-from-local')
    expect(getAuthItem(TOKEN_KEY)).toBe('webview-access-from-local')
  })

  it('reads the localStorage token even when a stale sessionStorage value exists', async () => {
    const { getAuthItem, TOKEN_KEY } = await import('@/api/authStorage')
    // 旧ビルドが WebViewPlayer 用に残した sessionStorage の値は拾わず、localStorage を読む。
    sessionStorage.setItem(TOKEN_KEY, 'stale-session')
    localStorage.setItem(TOKEN_KEY, 'webview-access-from-local')
    expect(getAuthItem(TOKEN_KEY)).toBe('webview-access-from-local')
  })

  it('returns null when no token is stored anywhere', async () => {
    const { getAuthItem, TOKEN_KEY } = await import('@/api/authStorage')
    expect(getAuthItem(TOKEN_KEY)).toBeNull()
  })
})
