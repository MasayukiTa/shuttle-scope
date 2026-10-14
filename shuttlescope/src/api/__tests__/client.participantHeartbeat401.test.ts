import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('apiPost 401 handling for participant heartbeat', () => {
  beforeEach(() => {
    sessionStorage.clear()
    vi.resetModules()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
    sessionStorage.clear()
  })

  it('heartbeat 401 does not call /auth/refresh and surfaces status 401', async () => {
    // 操作者の JWT が(別タブ等で)残っていても、参加者ハートビートの 401 で refresh しない
    sessionStorage.setItem('shuttlescope_token', 'access-old')
    sessionStorage.setItem('shuttlescope_refresh_token', 'refresh-old')
    const fetchMock = vi.fn(async () => jsonResponse({ detail: 'unauthorized' }, 401))
    vi.stubGlobal('fetch', fetchMock)
    const { apiPost } = await import('@/api/client')

    await expect(
      apiPost('/sessions/ABC/devices/7/heartbeat', { participant_token: 't' }),
    ).rejects.toMatchObject({ status: 401 })

    const urls = fetchMock.mock.calls.map((c) => String((c as unknown[])[0]))
    expect(urls.some((u) => u.includes('/auth/refresh'))).toBe(false)
    expect(urls).toHaveLength(1)
  })

  it('a normal API 401 still goes through the refresh path', async () => {
    sessionStorage.setItem('shuttlescope_token', 'access-old')
    sessionStorage.setItem('shuttlescope_refresh_token', 'refresh-old')
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/auth/refresh')) {
        return jsonResponse({ data: { access_token: 'a2', refresh_token: 'r2' } })
      }
      return jsonResponse({ detail: 'unauthorized' }, 401)
    })
    vi.stubGlobal('fetch', fetchMock)
    const { apiPost } = await import('@/api/client')

    await apiPost('/players', {}).catch(() => undefined)

    const urls = fetchMock.mock.calls.map((c) => String((c as unknown[])[0]))
    expect(urls.some((u) => u.includes('/auth/refresh'))).toBe(true)
  })
})
