import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiTimeoutError, fetchWithTimeout } from '@/api/client'

describe('fetchWithTimeout', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('returns the response when the server answers in time', async () => {
    const res = { ok: true, status: 200 }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(res))
    await expect(fetchWithTimeout('http://x/api/a', {}, 1000)).resolves.toBe(res)
  })

  it('aborts a request that never answers and raises ApiTimeoutError', async () => {
    vi.useFakeTimers()
    vi.stubGlobal(
      'fetch',
      vi.fn((_url: string, init: RequestInit) => new Promise((_resolve, reject) => {
        init.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
      })),
    )
    const p = fetchWithTimeout('http://x/api/hang', {}, 500)
    const assertion = expect(p).rejects.toBeInstanceOf(ApiTimeoutError)
    await vi.advanceTimersByTimeAsync(501)
    await assertion
  })

  it('passes ordinary network errors through unchanged', async () => {
    const boom = new TypeError('Failed to fetch')
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(boom))
    await expect(fetchWithTimeout('http://x/api/a', {}, 1000)).rejects.toBe(boom)
  })
})
