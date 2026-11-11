/**
 * カメラ送信: 読み込み中/失敗時の案内 (muse T011)。
 *
 * 症状:
 *   送信ページ (#/camera/<code>) を開くと最初に『接続中…』のスピナーだけが出て、
 *   参加フォームが出るまで 10〜25 秒かかる。待つあいだも失敗時も次の手の案内が無い。
 *
 * 直し:
 *   (1) 参加フォームは通信の確認 (resolveBaseUrl のヘルスチェック + join 往復) を
 *       待たずに先に出す。pwd 無しの QR 来訪では connecting 中でもフォームを描画する。
 *   (2) connecting が 5 秒を超えたら connecting_slow の案内を出す。
 *
 * 本テストは CameraSenderPage を実描画し、通信 (fetch) を未解決のままにしても
 * フォームが即出ること、そして fake timers で 5 秒進めると connecting_slow 文言が
 * 出ることを固定する。先行の承認待ちフロー (#298) を壊さないよう辞書キーは追加のみ。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

import ja from '@/i18n/ja.json'

const wsUrlMock = vi.fn<() => Promise<string>>()
vi.mock('@/utils/cameraWs', () => ({
  participantWsUrl: (..._args: unknown[]) => wsUrlMock(),
}))
vi.mock('@/hooks/useDeviceHeartbeat', () => ({ useDeviceHeartbeat: () => {} }))
vi.mock('@/hooks/session/useServerSideRecording', () => ({
  useServerSideRecording: () => ({ state: 'idle', errorMsg: null, stop: vi.fn() }),
}))

import i18n from '@/i18n'
import { CameraSenderPage } from '../CameraSenderPage'

class FakeWebSocket {
  onopen: (() => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  onmessage: ((e: MessageEvent) => void) | null = null
  constructor(public url: string) {}
  send() {}
  close() {}
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
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
    wsUrlMock.mockReset()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('pwd 無しの QR 来訪は、通信の確認を待たずに参加フォームを先に出す', async () => {
    // fetch を never-resolve にして『通信の確認待ち』を再現する。
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => {})))
    await act(async () => {
      renderAt('/camera/ABC123')
    })
    // 通信が未解決でも、参加フォーム (パスワード入力ラベル) が即座に出ている。
    expect(screen.getByLabelText(ja.camera_sender.join_password_label)).toBeTruthy()
  })

  it('接続中が 5 秒を超えたら connecting_slow の案内を出す', async () => {
    vi.useFakeTimers()
    // pwd 付き QR → 自動 join。fetch を never-resolve にして connecting を継続させる。
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => {})))
    await act(async () => {
      renderAt('/camera/ABC123?pwd=secret')
    })
    // 5 秒経過前は案内なし。
    expect(screen.queryByText(ja.camera_sender.connecting_slow)).toBeNull()
    await act(async () => {
      vi.advanceTimersByTime(5000)
    })
    expect(screen.getByText(ja.camera_sender.connecting_slow)).toBeTruthy()
  })
})
