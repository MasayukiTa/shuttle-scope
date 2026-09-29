import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

describe('api client auth refresh races', () => {
  beforeEach(() => {
    sessionStorage.clear()
    vi.resetModules()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
    sessionStorage.clear()
  })

  it('single-flights concurrent 401 refresh and retries both requests with the rotated token', async () => {
    sessionStorage.setItem('shuttlescope_token', 'access-old')
    sessionStorage.setItem('shuttlescope_refresh_token', 'refresh-old')

    const refreshGate = deferred<Response>()
    let refreshCalls = 0
    let dataCalls = 0
    const authSeen: string[] = []

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/auth/refresh')) {
        refreshCalls += 1
        return refreshGate.promise
      }

      dataCalls += 1
      const headers = (init?.headers ?? {}) as Record<string, string>
      authSeen.push(headers.Authorization ?? '')
      if (dataCalls <= 2) {
        return jsonResponse({ detail: 'expired access token' }, 401)
      }
      return jsonResponse({ ok: true, call: dataCalls })
    })
    vi.stubGlobal('fetch', fetchMock)

    const { apiGet } = await import('@/api/client')
    const p1 = apiGet<{ ok: boolean }>('/race-a')
    const p2 = apiGet<{ ok: boolean }>('/race-b')

    await vi.waitFor(() => expect(refreshCalls).toBe(1))
    refreshGate.resolve(jsonResponse({
      access_token: 'access-new',
      refresh_token: 'refresh-new',
    }))

    const [a, b] = await Promise.all([p1, p2])
    expect(a.ok).toBe(true)
    expect(b.ok).toBe(true)
    expect(refreshCalls).toBe(1)
    expect(dataCalls).toBe(4)
    expect(authSeen.slice(0, 2)).toEqual(['Bearer access-old', 'Bearer access-old'])
    expect(authSeen.slice(2)).toEqual(['Bearer access-new', 'Bearer access-new'])
    expect(sessionStorage.getItem('shuttlescope_token')).toBe('access-new')
    expect(sessionStorage.getItem('shuttlescope_refresh_token')).toBe('refresh-new')
  })

  it('does not let an old refresh success overwrite a newly logged-in user', async () => {
    sessionStorage.setItem('shuttlescope_token', 'access-user-a')
    sessionStorage.setItem('shuttlescope_refresh_token', 'refresh-user-a')

    const refreshGate = deferred<Response>()
    let refreshCalls = 0
    let resourceCalls = 0

    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/auth/refresh')) {
        refreshCalls += 1
        return refreshGate.promise
      }
      resourceCalls += 1
      return jsonResponse({ detail: 'expired access token' }, 401)
    }))

    const { apiGet } = await import('@/api/client')
    const pending = apiGet('/sensitive-old-request')

    await vi.waitFor(() => expect(refreshCalls).toBe(1))

    // Simulate logout + login as a different user before the old refresh returns.
    sessionStorage.setItem('shuttlescope_token', 'access-user-b')
    sessionStorage.setItem('shuttlescope_refresh_token', 'refresh-user-b')

    refreshGate.resolve(jsonResponse({
      access_token: 'access-user-a-rotated',
      refresh_token: 'refresh-user-a-rotated',
    }))

    await expect(pending).rejects.toMatchObject({ status: 401 })

    expect(resourceCalls).toBe(1)
    expect(sessionStorage.getItem('shuttlescope_token')).toBe('access-user-b')
    expect(sessionStorage.getItem('shuttlescope_refresh_token')).toBe('refresh-user-b')
  })

  it('does not let an old refresh 401 log out a newly logged-in user', async () => {
    sessionStorage.setItem('shuttlescope_token', 'access-user-a')
    sessionStorage.setItem('shuttlescope_refresh_token', 'refresh-user-a')

    const refreshGate = deferred<Response>()
    let refreshCalls = 0
    let resourceCalls = 0

    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/auth/refresh')) {
        refreshCalls += 1
        return refreshGate.promise
      }
      resourceCalls += 1
      return jsonResponse({ detail: 'expired access token' }, 401)
    }))

    const { apiGet } = await import('@/api/client')
    const pending = apiGet('/sensitive-old-request')

    await vi.waitFor(() => expect(refreshCalls).toBe(1))

    sessionStorage.setItem('shuttlescope_token', 'access-user-b')
    sessionStorage.setItem('shuttlescope_refresh_token', 'refresh-user-b')

    refreshGate.resolve(jsonResponse({ detail: 'old refresh revoked' }, 401))

    await expect(pending).rejects.toMatchObject({ status: 401 })

    expect(resourceCalls).toBe(1)
    expect(sessionStorage.getItem('shuttlescope_token')).toBe('access-user-b')
    expect(sessionStorage.getItem('shuttlescope_refresh_token')).toBe('refresh-user-b')
  })

  it('allows the new auth generation to refresh while the old generation is still in flight', async () => {
    sessionStorage.setItem('shuttlescope_token', 'access-user-a')
    sessionStorage.setItem('shuttlescope_refresh_token', 'refresh-user-a')

    const oldRefreshGate = deferred<Response>()
    const refreshTokensSeen: string[] = []
    let oldResourceCalls = 0
    let newResourceCalls = 0

    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/auth/refresh')) {
        const body = JSON.parse(String(init?.body ?? '{}')) as { refresh_token?: string }
        refreshTokensSeen.push(body.refresh_token ?? '')
        if (body.refresh_token === 'refresh-user-a') {
          return oldRefreshGate.promise
        }
        if (body.refresh_token === 'refresh-user-b') {
          return jsonResponse({
            access_token: 'access-user-b-rotated',
            refresh_token: 'refresh-user-b-rotated',
          })
        }
        throw new Error('unexpected refresh token')
      }

      if (url.includes('/old-generation')) {
        oldResourceCalls += 1
        return jsonResponse({ detail: 'old access expired' }, 401)
      }

      if (url.includes('/new-generation')) {
        newResourceCalls += 1
        if (newResourceCalls === 1) {
          return jsonResponse({ detail: 'new access also expired' }, 401)
        }
        const headers = (init?.headers ?? {}) as Record<string, string>
        expect(headers.Authorization).toBe('Bearer access-user-b-rotated')
        return jsonResponse({ ok: true })
      }

      throw new Error(`unexpected request: ${url}`)
    }))

    const { apiGet } = await import('@/api/client')
    const oldPending = apiGet('/old-generation')
    await vi.waitFor(() => expect(refreshTokensSeen).toContain('refresh-user-a'))

    // Switch accounts while A's refresh is still pending.
    sessionStorage.setItem('shuttlescope_token', 'access-user-b')
    sessionStorage.setItem('shuttlescope_refresh_token', 'refresh-user-b')

    const newResult = await apiGet<{ ok: boolean }>('/new-generation')
    expect(newResult.ok).toBe(true)
    expect(refreshTokensSeen).toEqual(['refresh-user-a', 'refresh-user-b'])

    // A returns late. Its result is superseded and cannot overwrite B.
    oldRefreshGate.resolve(jsonResponse({
      access_token: 'access-user-a-rotated',
      refresh_token: 'refresh-user-a-rotated',
    }))
    await expect(oldPending).rejects.toMatchObject({ status: 401 })

    expect(oldResourceCalls).toBe(1)
    expect(newResourceCalls).toBe(2)
    expect(sessionStorage.getItem('shuttlescope_token')).toBe('access-user-b-rotated')
    expect(sessionStorage.getItem('shuttlescope_refresh_token')).toBe('refresh-user-b-rotated')
  })

})
