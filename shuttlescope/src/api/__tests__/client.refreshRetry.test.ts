import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// fix/auth-session-persist: CI/ローカルの高負荷時でも forks ワーカー起動や
// 実時間 sleep(150ms)×再試行で既定 5s を超えることがあるため、待機上限のみ広げる
// (アサーションは不変)。
vi.setConfig({ testTimeout: 20000 })

// fix/auth-session-persist: refresh が一過性の network error で落ちたとき、同じ
// refresh token で短い待機のあと 1 回だけ再試行する挙動を検証する。サーバ側は
// 猶予時間内の再提示を冪等化している (同じ後継 refresh を返す) ので、再送しても安全。

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('refresh retries once on a transient network failure', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.resetModules()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
    localStorage.clear()
  })

  it('retries the refresh POST after a network error and then succeeds', async () => {
    localStorage.setItem('shuttlescope_token', 'access-old')
    localStorage.setItem('shuttlescope_refresh_token', 'refresh-old')

    let refreshAttempts = 0
    const refreshTokensSeen: string[] = []
    const authSeen: string[] = []

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/auth/refresh')) {
        refreshAttempts += 1
        const body = JSON.parse(String(init?.body ?? '{}')) as { refresh_token?: string }
        refreshTokensSeen.push(body.refresh_token ?? '')
        // 1 回目は network error (例外) を投げ、2 回目で成功させる。
        if (refreshAttempts === 1) {
          throw new TypeError('Failed to fetch')
        }
        return jsonResponse({ access_token: 'access-new', refresh_token: 'refresh-new' })
      }
      const headers = (init?.headers ?? {}) as Record<string, string>
      authSeen.push(headers.Authorization ?? '')
      // 1 回目の業務 API は 401 → refresh を誘発。2 回目は新 token で成功。
      return authSeen.length === 1 ? jsonResponse({ detail: 'expired' }, 401) : jsonResponse({ ok: true })
    })
    vi.stubGlobal('fetch', fetchMock)

    const { fetchAuthed } = await import('@/api/client')
    const res = await fetchAuthed('http://x/api/llm/send', { method: 'POST', body: '{}' })

    // 最終的に元リクエストは成功する。
    expect(res.status).toBe(200)
    // refresh は 2 回試行され、どちらも同じ (古い) refresh token を送っている。
    expect(refreshAttempts).toBe(2)
    expect(refreshTokensSeen).toEqual(['refresh-old', 'refresh-old'])
    // 2 回目の成功で token は更新され、元リクエストは新 access token で replay された。
    expect(localStorage.getItem('shuttlescope_refresh_token')).toBe('refresh-new')
    expect(authSeen).toEqual(['Bearer access-old', 'Bearer access-new'])
  })

  it('gives up (keeps the refresh token) when both attempts fail', async () => {
    localStorage.setItem('shuttlescope_token', 'access-old')
    localStorage.setItem('shuttlescope_refresh_token', 'refresh-old')

    let refreshAttempts = 0
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/auth/refresh')) {
        refreshAttempts += 1
        throw new TypeError('Failed to fetch')
      }
      return jsonResponse({ detail: 'expired' }, 401)
    })
    vi.stubGlobal('fetch', fetchMock)

    const { apiGet } = await import('@/api/client')
    await expect(apiGet('/slow-refresh')).rejects.toMatchObject({ status: 401 })

    // 2 回試行して諦める。valid な refresh token は決して捨てない (transient 扱い)。
    expect(refreshAttempts).toBe(2)
    expect(localStorage.getItem('shuttlescope_refresh_token')).toBe('refresh-old')
    expect(localStorage.getItem('shuttlescope_token')).toBe('access-old')
  })
})
