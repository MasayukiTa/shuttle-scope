/**
 * fix/auth-readers-video: PR #258 で認証の保存先が localStorage だけになったが、
 * src/components/video/WebViewPlayer.tsx と src/components/session/YouTubeLivePanel.tsx は
 * sessionStorage.getItem('shuttlescope_token') で直接読み、ログイン後も常に空に
 * なっていた。該当箇所を authStorage の getAuthItem(TOKEN_KEY) に置き換えた。
 *
 * このテストは 2 点を固定する:
 *   (1) localStorage にトークンを入れた状態で、両ファイルが通る getAuthItem(TOKEN_KEY)
 *       がそのトークンを返すこと。
 *   (2) 両ファイルの source が getAuthItem(TOKEN_KEY) を経由し、
 *       sessionStorage.getItem('shuttlescope_token') でトークンを直読みしていないこと
 *       (リグレッション防止)。コンポーネント全体の mount は重く環境依存が大きい
 *       ため、該当配線を source で静的に固定する。
 */
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const webViewSource = readFileSync(
  resolve(here, '../WebViewPlayer.tsx'),
  'utf-8',
)
const youtubeLiveSource = readFileSync(
  resolve(here, '../../session/YouTubeLivePanel.tsx'),
  'utf-8',
)

describe('video/session auth readers go through localStorage via getAuthItem', () => {
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

  it('WebViewPlayer.tsx reads the token via getAuthItem(TOKEN_KEY), not sessionStorage', () => {
    expect(webViewSource).toMatch(/getAuthItem\(TOKEN_KEY\)/)
    expect(webViewSource).toContain("from '@/api/authStorage'")
    // トークンを sessionStorage から直読みしていないこと。
    expect(webViewSource).not.toMatch(
      /sessionStorage\.getItem\(\s*'shuttlescope_token'\s*\)/,
    )
  })

  it('YouTubeLivePanel.tsx reads the token via getAuthItem(TOKEN_KEY), not sessionStorage', () => {
    expect(youtubeLiveSource).toMatch(/getAuthItem\(TOKEN_KEY\)/)
    expect(youtubeLiveSource).toContain("from '../../api/authStorage'")
    expect(youtubeLiveSource).not.toMatch(
      /sessionStorage\.getItem\(\s*'shuttlescope_token'\s*\)/,
    )
  })
})
