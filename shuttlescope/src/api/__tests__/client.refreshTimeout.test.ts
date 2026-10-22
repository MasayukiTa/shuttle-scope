import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

// abort されるまで応答しない fetch (TCP は成立したが応答が返らない半断)
function hangingFetch(_url: string, init?: RequestInit): Promise<Response> {
  return new Promise((_resolve, reject) => {
    init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
  })
}

describe('api client timeouts on the refresh and health paths', () => {
  beforeEach(() => {
    sessionStorage.clear()
    vi.resetModules()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
    sessionStorage.clear()
  })

  it('does not freeze an API call when /auth/refresh never answers', async () => {
    vi.useFakeTimers()
    sessionStorage.setItem('shuttlescope_token', 'access-old')
    sessionStorage.setItem('shuttlescope_refresh_token', 'refresh-old')

    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/auth/refresh')) return hangingFetch(url, init)
      return Promise.resolve(jsonResponse({ detail: 'expired' }, 401))
    })
    vi.stubGlobal('fetch', fetchMock)

    const { apiGet, REFRESH_TIMEOUT_MS } = await import('@/api/client')
    const p = apiGet('/slow-refresh')
    const assertion = expect(p).rejects.toMatchObject({ status: 401 })
    await vi.advanceTimersByTimeAsync(REFRESH_TIMEOUT_MS + 1)
    await assertion

    // transient 扱い: 有効な refresh token を捨てない (login-bounce 対策)
    expect(sessionStorage.getItem('shuttlescope_refresh_token')).toBe('refresh-old')
    expect(sessionStorage.getItem('shuttlescope_token')).toBe('access-old')
  })

  it('checkHealth returns false instead of hanging when /health never answers', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => hangingFetch(String(input), init)))

    const { checkHealth, HEALTH_TIMEOUT_MS } = await import('@/api/client')
    const p = checkHealth()
    await vi.advanceTimersByTimeAsync(HEALTH_TIMEOUT_MS + 1)
    await expect(p).resolves.toBe(false)
  })

  it('checkHealth returns true when the server answers', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ ok: true })))
    const { checkHealth } = await import('@/api/client')
    await expect(checkHealth()).resolves.toBe(true)
  })

  it('fetchAuthed refreshes once on 401 and replays the request with the new token', async () => {
    sessionStorage.setItem('shuttlescope_token', 'access-old')
    sessionStorage.setItem('shuttlescope_refresh_token', 'refresh-old')

    const authSeen: string[] = []
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/auth/refresh')) {
        return jsonResponse({ access_token: 'access-new', refresh_token: 'refresh-new' })
      }
      const headers = (init?.headers ?? {}) as Record<string, string>
      authSeen.push(headers.Authorization ?? '')
      return authSeen.length === 1 ? jsonResponse({ detail: 'expired' }, 401) : jsonResponse({ ok: true })
    })
    vi.stubGlobal('fetch', fetchMock)

    const { fetchAuthed } = await import('@/api/client')
    const res = await fetchAuthed('http://x/api/llm/send', { method: 'POST', body: '{}' })
    expect(res.status).toBe(200)
    expect(authSeen).toEqual(['Bearer access-old', 'Bearer access-new'])
  })
})
