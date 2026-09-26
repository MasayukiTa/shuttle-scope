/**
 * U-2: streaming アップロードは 1 本ずつ・順番どおりでなければならない。
 *
 * サーバ (`backend/routers/uploads.py`) は streaming モードで
 * `chunk_index != session.received_count` を 409 にする。つまり
 * **同時に 2 本走らせてはいけない**。
 *
 * 旧実装は `ondataavailable` で `void uploadChunk(e.data, idx)` と投げっぱなしに
 * しており、回線が揺れて n+1 が n より先に着くと 409。逐次前提のサーバでは
 * 1 個弾かれた時点で以後すべて 409 になるので、**そこで録画が終わる**。
 * 画面は「録画中」のままなので、操作者は録れていると信じ続ける。
 *
 * ここで固定するのは 2 点:
 *   1. 同時に飛ぶ chunk POST は常に 1 本
 *   2. chunk_index は 0 から連番で、順序が入れ替わらない
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, renderHook } from '@testing-library/react'

import { useServerSideRecording } from '@/hooks/session/useServerSideRecording'

// ─── MediaRecorder の最小スタブ ────────────────────────────────────────────
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

/** 実際に飛んだ chunk POST を観測する。 */
interface Observed {
  order: number[]
  maxConcurrent: number
}

function installFetch(observed: Observed, opts: { failAt?: number } = {}) {
  let inFlight = 0
  let received = 0
  return vi.fn(async (url: unknown, init?: { body?: unknown }) => {
    const u = String(url)
    if (u.includes('/uploads/video/init')) {
      return { ok: true, status: 200, json: async () => ({ success: true, data: { upload_id: 'u1', chunk_size: 8, total_chunks: 0 } }), text: async () => '' }
    }
    if (u.includes('/uploads/video/chunk')) {
      inFlight += 1
      observed.maxConcurrent = Math.max(observed.maxConcurrent, inFlight)
      const fd = init?.body as FormData
      const idx = Number(fd.get('chunk_index'))
      // ネットワークの揺らぎを模す。**あとの chunk ほど速く返す**ので、
      // 並行に投げている実装では到着順が入れ替わる（= サーバの 409 規則に触れる）。
      // 一定待ちにすると投げた順のまま返ってしまい、この検査が何も見なくなる。
      await new Promise((r) => setTimeout(r, Math.max(2, 40 - idx * 8)))
      inFlight -= 1
      if (opts.failAt === idx && !observed.order.includes(idx)) {
        return { ok: false, status: 503, text: async () => 'boom' }   // 一過性
      }
      // サーバと同じ規則で拒否する
      if (idx !== received) {
        return { ok: false, status: 409, text: async () => `expected=${received} got=${idx}` }
      }
      received += 1
      observed.order.push(idx)
      return { ok: true, status: 200, json: async () => ({}), text: async () => '' }
    }
    return { ok: true, status: 200, json: async () => ({}), text: async () => '' }
  })
}

describe('useServerSideRecording — streaming upload ordering', () => {
  let observed: Observed

  beforeEach(() => {
    observed = { order: [], maxConcurrent: 0 }
    vi.stubGlobal('MediaRecorder', FakeMediaRecorder)
    vi.stubGlobal('sessionStorage', {
      getItem: () => 'token', setItem: () => {}, removeItem: () => {},
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  async function recordChunks(count: number, failAt?: number) {
    vi.stubGlobal('fetch', installFetch(observed, { failAt }))
    const { result } = renderHook(() => useServerSideRecording({ matchId: 1, timesliceSec: 1 }))
    let recorder: FakeMediaRecorder | null = null
    const origCtor = FakeMediaRecorder
    vi.stubGlobal('MediaRecorder', class extends origCtor {
      constructor(s: unknown, o: unknown) { super(s, o); recorder = this as unknown as FakeMediaRecorder }
    })
    await act(async () => {
      await result.current.start({} as MediaStream)
    })
    expect(recorder, 'MediaRecorder が作られていない').not.toBeNull()
    await act(async () => {
      for (let i = 0; i < count; i++) {
        recorder!.ondataavailable?.({ data: new Blob([new Uint8Array([1, 2, 3])]) })
      }
      // ポンプが流れ切るのを待つ
      await new Promise((r) => setTimeout(r, 60 * count))
    })
    return result
  }

  it('同時に飛ぶ chunk POST は 1 本だけ', async () => {
    await recordChunks(5)
    expect(observed.maxConcurrent).toBe(1)
  })

  it('chunk_index は 0 から連番で届く（サーバの 409 規則に一度も触れない）', async () => {
    await recordChunks(5)
    expect(observed.order).toEqual([0, 1, 2, 3, 4])
  })

  it('一過性の 5xx のあとも順序が崩れない', async () => {
    // index 2 を一度だけ 503 にする。先頭に残して再送されるので、
    // 3 以降が 2 を追い越してはいけない。
    await recordChunks(5, 2)
    const sorted = [...observed.order].sort((a, b) => a - b)
    expect(observed.order).toEqual(sorted)
    expect(observed.order[0]).toBe(0)
  })
  it('QR participant credential is used for init, chunk, and finalize', async () => {
    const fetchMock = installFetch(observed)
    vi.stubGlobal('fetch', fetchMock)
    let recorder: FakeMediaRecorder | null = null
    const origCtor = FakeMediaRecorder
    vi.stubGlobal('MediaRecorder', class extends origCtor {
      constructor(s: unknown, o: unknown) { super(s, o); recorder = this as unknown as FakeMediaRecorder }
    })
    const { result } = renderHook(() => useServerSideRecording({
      matchId: 1,
      sessionCode: 'SESSION1',
      participantId: 42,
      participantToken: 'participant-secret',
      timesliceSec: 1,
    }))

    await act(async () => { await result.current.start({} as MediaStream) })
    expect(recorder).not.toBeNull()

    await act(async () => {
      recorder!.ondataavailable?.({ data: new Blob([new Uint8Array([1, 2, 3])]) })
      await new Promise((r) => setTimeout(r, 80))
    })

    await act(async () => { await result.current.stop() })

    const calls = fetchMock.mock.calls.map(([url, init]) => ({ url: String(url), init }))
    for (const suffix of ['/uploads/video/init', '/uploads/video/chunk', '/finalize']) {
      const matching = calls.filter(({ url }) => url.includes(suffix))
      expect(matching.length, `missing ${suffix}`).toBeGreaterThan(0)
      const hasParticipantAuth = matching.some(({ init }) => {
        const headers = init?.headers as Record<string, string> | undefined
        return headers?.Authorization === 'Participant participant-secret'
          && headers['X-Session-Code'] === 'SESSION1'
          && headers['X-Participant-Id'] === '42'
      })
      expect(hasParticipantAuth, `participant auth missing on ${suffix}`).toBe(true)
    }
  })

})
