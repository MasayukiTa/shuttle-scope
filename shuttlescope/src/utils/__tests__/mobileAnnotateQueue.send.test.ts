import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { trySend, QUEUE_SEND_TIMEOUT_MS, type QueueItem } from '../mobileAnnotateQueue'

function jwt(payload: Record<string, unknown>): string {
  const b64 = (o: unknown) => btoa(JSON.stringify(o)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
  return `${b64({ alg: 'HS256', typ: 'JWT' })}.${b64(payload)}.sig`
}

function queued(ownerUserId: number): QueueItem {
  return {
    localId: 1,
    clientUuid: 'u-1',
    endpoint: 'PUT /api/strokes/:id',
    pathParams: { id: 5 },
    body: { shot_type: 'clear' },
    attempts: 0,
    nextAttemptAt: 0,
    manualRetry: false,
    queuedAt: 1,
    ownerUserId,
  }
}

function resp(status: number, body: unknown = {}): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(body),
    json: async () => body,
  } as unknown as Response
}

describe('mobileAnnotateQueue.trySend', () => {
  beforeEach(() => {
    sessionStorage.clear()
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    sessionStorage.clear()
  })

  it('refreshes the token once on 401 and resends with the new token', async () => {
    const oldTok = jwt({ sub: 9 })
    const newTok = jwt({ sub: 9, n: 2 })
    sessionStorage.setItem('shuttlescope_token', oldTok)
    sessionStorage.setItem('shuttlescope_refresh_token', 'rt-1')
    const calls: Array<{ url: string; auth?: string }> = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit) => {
      const headers = (init.headers ?? {}) as Record<string, string>
      calls.push({ url, auth: headers.Authorization })
      if (url.includes('/auth/refresh')) {
        return resp(200, { access_token: newTok, refresh_token: 'rt-2' })
      }
      return headers.Authorization === `Bearer ${newTok}` ? resp(200) : resp(401)
    }))

    await expect(trySend(queued(9))).resolves.toBe('ok')
    const sends = calls.filter((c) => c.url.includes('/api/strokes/5'))
    expect(sends).toHaveLength(2)
    expect(sends[0].auth).toBe(`Bearer ${oldTok}`)
    expect(sends[1].auth).toBe(`Bearer ${newTok}`)
    expect(calls.filter((c) => c.url.includes('/auth/refresh'))).toHaveLength(1)
  })

  it('keeps the item for later (auth) when refresh is rejected', async () => {
    sessionStorage.setItem('shuttlescope_token', jwt({ sub: 9 }))
    sessionStorage.setItem('shuttlescope_refresh_token', 'rt-1')
    vi.stubGlobal('fetch', vi.fn(async (url: string) => (
      url.includes('/auth/refresh') ? resp(401) : resp(401)
    )))
    await expect(trySend(queued(9))).resolves.toBe('auth')
  })

  it('does not hang on a half-open connection: times out and is retried', async () => {
    vi.useFakeTimers()
    sessionStorage.setItem('shuttlescope_token', jwt({ sub: 9 }))
    vi.stubGlobal('fetch', vi.fn((_url: string, init: RequestInit) => new Promise((_res, rej) => {
      init.signal?.addEventListener('abort', () => rej(new DOMException('aborted', 'AbortError')))
    })))
    const it1 = queued(9)
    const p = trySend(it1)
    await vi.advanceTimersByTimeAsync(QUEUE_SEND_TIMEOUT_MS + 1)
    await expect(p).resolves.toBe('retry')
    expect(it1.lastError).toContain('timeout')
  })
})
