/**
 * カメラ送信: 読み込み中の案内 (muse T011)。
 *
 * 症状:
 *   送信ページ (#/camera/<コード>) を開くと「接続中...」のスピナーだけが
 *   10～25 秒出続け、待つあいだも失敗したときも次の手の案内が無かった。
 *
 * このテストは次を固定する:
 *   (1) 参加フォームは通信の確認 (health check / join / ws-ticket) を
 *       待たずに先に出る。pwd なし URL で開いたら、fetch が 1 度も
 *       解決しなくてもコード入力欄が即表示される。
 *   (2) 接続待ち (connecting) が 5 秒を超えたら電波確認の案内を出す。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, act } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

// participantWsUrl は決して resolve しない Promise にして connecting を維持する。
const wsUrlMock = vi.fn<() => Promise<string>>()
vi.mock('@/utils/cameraWs', () => ({
  participantWsUrl: (..._args: unknown[]) => wsUrlMock(),
}))

// heartbeat / 録画 / ICE は本テストの対象外。
vi.mock('@/hooks/useDeviceHeartbeat', () => ({ useDeviceHeartbeat: () => {} }))
vi.mock('@/hooks/session/useServerSideRecording', () => ({
  useServerSideRecording: () => ({ state: 'idle', errorMsg: null, stop: vi.fn() }),
}))

import i18n from '@/i18n'
import { CameraSenderPage } from '../CameraSenderPage'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

class FakeWebSocket {
  onopen: (() => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  onmessage: ((e: MessageEvent) => void) | null = null
  constructor(public url: string) {}
  send() {}
  close() {}
}

function renderAt(entry: string) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/camera/:sessionCode" element={<CameraSenderPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('CameraSenderPage loading guidance (T011)', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('ja')
    vi.stubGlobal('WebSocket', FakeWebSocket as unknown as typeof WebSocket)
    // join 応答は返すが、ws-ticket (participantWsUrl) は mock で止めるので
    // connecting が維持される。
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (String(url).includes('/join')) {
          return jsonResponse({
            success: true,
            data: { participant_id: 7, session_code: 'ABC123', role: 'viewer', connection_role: 'device', participant_token: 'ptok' },
          })
        }
        return jsonResponse({ success: true, data: {} })
      }),
    )
    wsUrlMock.mockReset()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('pwd なし URL では、通信の確認を待たずに参加フォーム (コード入力) が即出る', async () => {
    // participantWsUrl / join を一切呼ばないままでも、フォームが見えること。
    wsUrlMock.mockReturnValue(new Promise<string>(() => {}))
    renderAt('/camera/ABC123')
    // コード入力欄 (join フォーム) が即座に存在する。
    expect(screen.getByLabelText(i18n.t('camera_sender.join_code_label'))).toBeTruthy()
    // 通信を確認する join API はこの時点で呼ばれていない。
    expect((globalThis.fetch as unknown as ReturnType<typeof vi.fn>)).not.toHaveBeenCalled()
  })

  it('connecting が 5 秒を超えたら電波確認の案内 (slow_connection) を出す', async () => {
    vi.useFakeTimers()
    // ws-ticket を決して resolve しない Promise にして connecting を維持。
    wsUrlMock.mockReturnValue(new Promise<string>(() => {}))
    renderAt('/camera/ABC123?pwd=secret')
    // join を割り込ませて connecting に遷移させる。
    await act(async () => { await Promise.resolve() })
    // 5 秒未満では案内は出ない。
    expect(screen.queryByText(i18n.t('camera_sender.slow_connection'))).toBeNull()
    // 5 秒進める。
    await act(async () => { vi.advanceTimersByTime(5_000) })
    expect(screen.getByText(i18n.t('camera_sender.slow_connection'))).toBeTruthy()
  })
})

describe('loading guidance: dictionary + source invariants', () => {
  it('slow_connection / join_error_help キーが ja・en 両方にあり非空', async () => {
    const ja = (await import('@/i18n/ja.json')).default as Record<string, any>
    const en = (await import('@/i18n/en.json')).default as Record<string, any>
    for (const dict of [ja, en]) {
      const cs = dict.camera_sender as Record<string, unknown>
      for (const k of ['slow_connection', 'join_error_help']) {
        expect(typeof cs[k]).toBe('string')
        expect((cs[k] as string).length).toBeGreaterThan(0)
      }
    }
  })
})
