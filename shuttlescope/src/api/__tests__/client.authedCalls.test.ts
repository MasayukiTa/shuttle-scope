import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'

// 認証が必要な呼び出し (ファイル取得・ベンチマーク停止) が Bearer を付けること。

function newToken(): string {
  return `tok-${crypto.randomUUID()}`
}

describe('authenticated blob download and benchmark cancel', () => {
  beforeEach(() => {
    sessionStorage.clear()
    vi.resetModules()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
    sessionStorage.clear()
  })

  it('apiGetBlob sends the Bearer token and returns the blob with the server file name', async () => {
    const token = newToken()
    sessionStorage.setItem('shuttlescope_token', token)
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      new Response('payload', {
        status: 200,
        headers: { 'Content-Disposition': 'attachment; filename="fallback.json"; filename*=UTF-8\'\'match%20a.json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const { apiGetBlob } = await import('@/api/client')
    const out = await apiGetBlob('/export/package', { match_id: 7 })

    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toContain('/export/package?match_id=7')
    expect((init?.headers as Record<string, string>).Authorization).toBe(`Bearer ${token}`)
    expect(out.filename).toBe('match a.json')
    expect(out.blob.size).toBe('payload'.length)
  })

  it('apiGetBlob rejects with the HTTP status instead of returning an error body as a file', async () => {
    sessionStorage.setItem('shuttlescope_token', newToken())
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{"detail":"forbidden"}', { status: 403 })))

    const { apiGetBlob } = await import('@/api/client')
    await expect(apiGetBlob('/export/package', { match_id: 7 })).rejects.toMatchObject({ status: 403 })
  })

  it('filenameFromContentDisposition handles plain, quoted and missing headers', async () => {
    const { filenameFromContentDisposition } = await import('@/api/client')
    expect(filenameFromContentDisposition('attachment; filename="a.json"')).toBe('a.json')
    expect(filenameFromContentDisposition('attachment; filename=b.json')).toBe('b.json')
    expect(filenameFromContentDisposition(null)).toBeNull()
    expect(filenameFromContentDisposition('attachment')).toBeNull()
  })

  it('cancelJob goes through the shared client with the Bearer token', async () => {
    const token = newToken()
    sessionStorage.setItem('shuttlescope_token', token)
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      new Response(JSON.stringify({ success: true, job_id: 'j1' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const { cancelJob } = await import('@/api/benchmark')
    await cancelJob('j1')

    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toContain('/api/v1/benchmark/jobs/j1')
    expect(init?.method).toBe('DELETE')
    expect((init?.headers as Record<string, string>).Authorization).toBe(`Bearer ${token}`)
  })

  it('cancelJob surfaces a failure so the caller does not pretend the job stopped', async () => {
    sessionStorage.setItem('shuttlescope_token', newToken())
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{"detail":"nope"}', { status: 500 })))

    const { cancelJob } = await import('@/api/benchmark')
    await expect(cancelJob('j1')).rejects.toMatchObject({ status: 500 })
  })
})
