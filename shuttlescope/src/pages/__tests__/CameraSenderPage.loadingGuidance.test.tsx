/**
 * カメラ送信: 読み込み時の案内 (muse T011)。
 *
 * 症状:
 *   送信ページ (#/camera/<コード>?pwd=...) を開くと、最初に
 *   「接続中...」のスピナーだけが出て、参加フォームが出るまで
 *   10〜25 秒かかる。裏では経路選択(health check) + join + 入場券取得が
 *   進んでいるが、利用者には何も見えず「止まった」と感じられる。
 *
 * 直し方:
 *   - 参加フォームは通信の確認を待たず先に出す。connecting 中も
 *     コード/パスワード欄を描画する。
 *   - connecting が 5 秒を超えたら「接続に時間がかかっています」の
 *     案内 (slow_connecting) を出す。
 *
 * 本テストは実際に CameraSenderPage を描画し、participantWsUrl を永久に
 * pending にして connecting を維持した状態で、フォームが即描画されることと
 * 5 秒後に遅延案内が出ることを固定する。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, act } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

// participantWsUrl を永久 pending にして connecting を維持する。
const wsUrlMock = vi.fn<() => Promise<string>>()
vi.mock('@/utils/cameraWs', () => ({
  participantWsUrl: (..._args: unknown[]) => wsUrlMock(),
}))

// heartbeat / 録画 / ICE は本テストの対象外。
vi.mock('@/hooks/useDeviceHeartbeat', () => ({ useDeviceHeartbeat: () => {} }))
vi.mock('@/hooks/session/useServerSideRecording', () => ({
  useServerSideRecording: () => ({ state: 'idle', errorMsg: null, start: vi.fn(), stop: vi.fn() }),
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

function renderAt(code = 'ABC123') {
  return render(
    <MemoryRouter initialEntries={[`/camera/${code}?pwd=secret`]}>
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
    // 入場券取得を永久 pending にして connecting を維持。
    wsUrlMock.mockImplementation(() => new Promise<string>(() => {}))
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('QR から来た connecting 中でも、通信確認を待たず参加フォームを先に出す', async () => {
    renderAt()
    // コード/パスワード/端末名の入力欄が connecting 中でも存在する。
    await waitFor(() => {
      expect(screen.getByLabelText(i18n.t('camera_sender.join_code_label'))).toBeTruthy()
    })
    expect(screen.getByLabelText(i18n.t('camera_sender.join_password_label'))).toBeTruthy()
    // 接続中の状況表示も出ている。
    expect(screen.getByText(i18n.t('camera_sender.join_connecting'))).toBeTruthy()
  })

  it('connecting が 5 秒を超えたら slow_connecting の案内を出す', async () => {
    vi.useFakeTimers()
    renderAt()
    // 初期は slow 案内なし。
    expect(screen.queryByText(i18n.t('camera_sender.slow_connecting'))).toBeNull()
    // 5 秒進める。
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000)
    })
    expect(screen.getByText(i18n.t('camera_sender.slow_connecting'))).toBeTruthy()
  })
})
