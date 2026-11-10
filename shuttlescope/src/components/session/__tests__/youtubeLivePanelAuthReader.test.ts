import { readFileSync } from 'fs'
import { resolve } from 'path'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

// fix/auth-reader-youtube: PR #258 で認証の保存先が localStorage だけになったが、
// src/components/session/YouTubeLivePanel.tsx に sessionStorage.getItem('shuttlescope_token')
// で直接読む箱所が残り、常に空になっていた。該当箱所は authStorage の
// getAuthItem(TOKEN_KEY) に置き換えた。このテストは (1) localStorage に
// トークンを入れた状態で getAuthItem(TOKEN_KEY) がその値を返すこと、
// (2) YouTubeLivePanel が sessionStorage ではなく getAuthItem(TOKEN_KEY) 経由で
// トークンを読むことを確かめる。

describe('YouTubeLivePanel DRM token reader goes through localStorage via getAuthItem', () => {
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

  it('reads the localStorage token even when a stale sessionStorage value exists', async () => {
    const { getAuthItem, TOKEN_KEY } = await import('@/api/authStorage')
    // 旧ビルドが残した sessionStorage の値は拾わず、localStorage を読む。
    sessionStorage.setItem(TOKEN_KEY, 'stale-session')
    localStorage.setItem(TOKEN_KEY, 'access-from-local')
    expect(getAuthItem(TOKEN_KEY)).toBe('access-from-local')
  })

  it('YouTubeLivePanel.tsx reads the DRM token via getAuthItem(TOKEN_KEY), not sessionStorage', () => {
    const src = readFileSync(
      resolve(__dirname, '../YouTubeLivePanel.tsx'),
      'utf-8',
    )
    // 該当箱所が getAuthItem(TOKEN_KEY) を使う。
    expect(src).toContain('getAuthItem(TOKEN_KEY)')
    // sessionStorage でトークンを直読みしない。
    expect(src).not.toContain("sessionStorage.getItem('shuttlescope_token')")
  })
})
