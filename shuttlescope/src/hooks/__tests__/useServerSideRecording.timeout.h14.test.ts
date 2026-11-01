/**
 * #662: server-side recording の init / chunk / finalize はすべて有限 timeout の
 * fetchWithTimeout を通さなければならない。生 fetch だと半断 (TCP 接続済みで応答
 * が返らない) のとき 1 本が pending のまま残り、stop() の finalize 待ちが無期限に
 * 止まって ServerVideoArtifact が確定しない。
 *
 * ここでは fetchWithTimeout をモックして、3 つの経路すべてが用途別の有限 timeout
 * 引数付きで呼ばれることを確認する (timeout 値そのものの中断挙動は api/client 側で
 * 担保される)。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, renderHook } from '@testing-library/react'

// fetchWithTimeout を観測するためにモックする。
const fetchWithTimeout = vi.fn()
vi.mock('@/api/client', () => ({
  fetchWithTimeout: (...args: unknown[]) => fetchWithTimeout(...args),
}))

import { useServerSideRecording } from '@/hooks/session/useServerSideRecording'

class FakeMediaRecorder {
  static isTypeSupported() { return true }
  state = 'inactive'
  ondataavailable: ((e: { data: Blob }) => void) | null = null
  onerror: ((e: Event) => void) | null = null
  onstop: (() => void) | null = null
  constructor(_stream: unknown, _opts: unknown) { void _stream; void _opts }
  start() { this.state = 'recording' }
  stop() { this.state = 'inactive'; this.onstop?.() }
}

/** url ごとに成功レスポンスを返す。timeout 引数は呼び出し履歴で検証する。 */
function okResponse(url: string) {
  if (url.includes('/uploads/video/init')) {
    return { ok: true, status: 200, json: async () => ({ success: true, data: { upload_id: 'u1', chunk_size: 8, total_chunks: 0 } }), text: async () => '' }
  }
  return { ok: true, status: 200, json: async () => ({ success: true }), text: async () => '' }
}

describe('useServerSideRecording #662 timeouts', () => {
  let recorder: FakeMediaRecorder | null

  beforeEach(() => {
    recorder = null
    fetchWithTimeout.mockReset()
    fetchWithTimeout.mockImplementation(async (url: string) => okResponse(String(url)))
    vi.stubGlobal('MediaRecorder', class extends FakeMediaRecorder {
      constructor(s: unknown, o: unknown) { super(s, o); recorder = this as unknown as FakeMediaRecorder }
    })
    vi.stubGlobal('sessionStorage', { getItem: () => 'token', setItem: () => {}, removeItem: () => {} })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  function timeoutArgFor(suffix: string): number | undefined {
    const call = fetchWithTimeout.mock.calls.find(([u]) => String(u).includes(suffix))
    return call?.[2] as number | undefined
  }

  it('init / chunk / finalize はすべて有限 timeout 付きの fetchWithTimeout を通る', async () => {
    const { result } = renderHook(() => useServerSideRecording({ matchId: 1, timesliceSec: 1 }))
    await act(async () => { await result.current.start({} as MediaStream) })
    expect(recorder).not.toBeNull()

    await act(async () => {
      recorder!.ondataavailable?.({ data: new Blob([new Uint8Array([1, 2, 3])]) })
      await new Promise((r) => setTimeout(r, 80))
    })
    await act(async () => { await result.current.stop() })

    for (const suffix of ['/uploads/video/init', '/uploads/video/chunk', '/finalize']) {
      const called = fetchWithTimeout.mock.calls.some(([u]) => String(u).includes(suffix))
      expect(called, `${suffix} が呼ばれていない`).toBe(true)
      const t = timeoutArgFor(suffix)
      expect(typeof t, `${suffix} に timeout 引数がない`).toBe('number')
      expect(t, `${suffix} の timeout が有限で正であること`).toBeGreaterThan(0)
      expect(Number.isFinite(t as number)).toBe(true)
    }
  })
})
