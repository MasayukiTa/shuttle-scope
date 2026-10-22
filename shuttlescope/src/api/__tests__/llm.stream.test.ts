import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

function sseResponse(lines: string[]): Response {
  const body = lines.map((l) => `data: ${l}\n\n`).join('')
  return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
}

describe('LLM stream send', () => {
  beforeEach(() => {
    sessionStorage.clear()
    vi.resetModules()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
    sessionStorage.clear()
  })

  it('extractLlmErrorDetail never returns [object Object]', async () => {
    const { extractLlmErrorDetail } = await import('@/api/llm')
    expect(extractLlmErrorDetail({ error: 'budget_exceeded' })).toBe('budget_exceeded')
    expect(extractLlmErrorDetail('plain message')).toBe('plain message')
    expect(extractLlmErrorDetail({ code: 'x_code' })).toBe('x_code')
    expect(extractLlmErrorDetail({ nested: { a: 1 } })).toBeNull()
    expect(extractLlmErrorDetail(undefined)).toBeNull()
  })

  it('reports the structured 429 detail as a stable code', async () => {
    sessionStorage.setItem('shuttlescope_token', 'access')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: { error: 'budget_exceeded' } }), {
        status: 429,
        headers: { 'Content-Type': 'application/json' },
      }),
    ))
    const { streamMessage } = await import('@/api/llm')
    const events: Array<{ type: string; message?: string }> = []
    await streamMessage(1, 'hello', (e) => events.push(e))
    expect(events).toEqual([{ type: 'error', message: 'budget_exceeded' }])
  })

  it('refreshes the access token on 401 and resends the message once', async () => {
    sessionStorage.setItem('shuttlescope_token', 'access-old')
    sessionStorage.setItem('shuttlescope_refresh_token', 'refresh-old')
    const authSeen: string[] = []
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/auth/refresh')) {
        return new Response(JSON.stringify({ access_token: 'access-new', refresh_token: 'refresh-new' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      const headers = (init?.headers ?? {}) as Record<string, string>
      authSeen.push(headers.Authorization ?? '')
      if (authSeen.length === 1) {
        return new Response(JSON.stringify({ detail: 'expired' }), { status: 401 })
      }
      return sseResponse([JSON.stringify({ type: 'delta', content: 'hi' }), JSON.stringify({ type: 'done' })])
    })
    vi.stubGlobal('fetch', fetchMock)

    const { streamMessage } = await import('@/api/llm')
    const events: Array<{ type: string; content?: string }> = []
    await streamMessage(7, 'hello', (e) => events.push(e))
    expect(authSeen).toEqual(['Bearer access-old', 'Bearer access-new'])
    expect(events.map((e) => e.type)).toEqual(['delta', 'done'])
  })
})
