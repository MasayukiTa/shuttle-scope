/**
 * fix/sender-recording-participant-auth:
 * JWT を持たない送信端（QR カメラ）が participant_token だけで
 * 録画の確定（finalize）まで到達できること、および結果が
 * 利用者向けの文言で表示されることを検証する。
 *
 *   - 成功時: successMsg に 「録画を保存しました」
 *   - 401 時: errorMsg に認証原因が分かる文言
 *   - その他失敗: errorMsg に汎用の保存失敗文言
 *
 * 開発者向けの生ステータス/本文は利用者には出さない。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, renderHook } from '@testing-library/react'

import { useServerSideRecording } from '@/hooks/session/useServerSideRecording'
import i18n from '@/i18n'

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

/** finalize の HTTP ステータスを差し替えられる fetch スタブ。 */
function installFetch(finalizeStatus: number) {
  return vi.fn(async (url: unknown, init?: { headers?: unknown }) => {
    const u = String(url)
    if (u.includes('/uploads/video/init')) {
      return { ok: true, status: 200, json: async () => ({ success: true, data: { upload_id: 'u1', chunk_size: 8, total_chunks: 0 } }), text: async (): Promise<string> => '' }
    }
    if (u.includes('/uploads/video/chunk')) {
      return { ok: true, status: 200, json: async () => ({}), text: async (): Promise<string> => '' }
    }
    if (u.includes('/finalize')) {
      void init
      if (finalizeStatus === 200) {
        return { ok: true, status: 200, json: async () => ({ success: true }), text: async (): Promise<string> => '' }
      }
      return { ok: false, status: finalizeStatus, text: async (): Promise<string> => 'detail: authentication required' }
    }
    return { ok: true, status: 200, json: async () => ({}), text: async (): Promise<string> => '' }
  })
}

async function runParticipantRecording(finalizeStatus: number) {
  const fetchMock = installFetch(finalizeStatus)
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
  expect(recorder, 'MediaRecorder が作られていない').not.toBeNull()
  await act(async () => {
    recorder!.ondataavailable?.({ data: new Blob([new Uint8Array([1, 2, 3])]) })
    await new Promise((r) => setTimeout(r, 80))
  })
  await act(async () => { await result.current.stop() })
  return { result, fetchMock }
}

describe('useServerSideRecording — participant finalize (no JWT)', () => {
  beforeEach(() => {
    // JWT を持たない端末を再現するため、トークンは置かない。
    localStorage.clear()
    vi.stubGlobal('MediaRecorder', FakeMediaRecorder)
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
    localStorage.clear()
  })

  it('participant_token だけで init/chunk/finalize まで到達し、成功文言を出す', async () => {
    const { result, fetchMock } = await runParticipantRecording(200)
    const urls = fetchMock.mock.calls.map(([u]) => String(u))
    expect(urls.some((u) => u.includes('/uploads/video/init'))).toBe(true)
    expect(urls.some((u) => u.includes('/finalize'))).toBe(true)
    // JWT なしでも participant 認証ヘッダで finalize まで進む。
    const finalizeCall = fetchMock.mock.calls.find(([u]) => String(u).includes('/finalize'))
    const headers = (finalizeCall?.[1] as RequestInit | undefined)?.headers as Record<string, string> | undefined
    expect(headers?.Authorization).toBe('Participant participant-secret')
    expect(result.current.state).toBe('completed')
    expect(result.current.successMsg).toBe(i18n.t('camera_sender.recording_saved'))
    expect(result.current.errorMsg).toBeNull()
  })

  it('finalize 401 は認証原因が分かる文言を出し、生ステータスは出さない', async () => {
    const { result } = await runParticipantRecording(401)
    expect(result.current.state).toBe('error')
    expect(result.current.errorMsg).toBe(i18n.t('camera_sender.recording_auth_failed'))
    expect(result.current.errorMsg).not.toContain('401')
    expect(result.current.successMsg).toBeNull()
  })

  it('finalize のその他失敗は汎用の保存失敗文言を出す', async () => {
    const { result } = await runParticipantRecording(500)
    expect(result.current.state).toBe('error')
    expect(result.current.errorMsg).toBe(i18n.t('camera_sender.recording_save_failed'))
    expect(result.current.successMsg).toBeNull()
  })
})
