/**
 * カメラ送信: 読み込み中の案内 (T011)。
 *
 * 症状:
 *   送信ページ (#/camera/<コード>) を開くと「接続中…」のスピナーだけが出て、
 *   参加フォームが出るまで 10〜25 秒かかる。待つあいだも、失敗したときも、次の手の案内が無い。
 *
 * 本テストの固定する不変条件:
 *   1. paramCode が無い通常訪問では、参加フォームが通信の確認を待たずに即座に出る。
 *   2. paramCode 自動参加で connecting が 5 秒を超えたら「時間がかかっています」案内を出す。
 *   3. 通信エラーで最終的に error に落ちたら、次の手 (パスワードの確認先・電波・再試行) を出す。
 *   4. 辞書・ソースの構造不変条件 (先行の承認フローのガードを壊さない)。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { readFileSync } from 'fs'
import { resolve } from 'path'
import { render, screen, act } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

import ja from '@/i18n/ja.json'
import en from '@/i18n/en.json'

// participantWsUrl の戻りで接続可否を制御する。
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

function renderWithCode(code = 'ABC123') {
  return render(
    <MemoryRouter initialEntries={[`/camera/${code}?pwd=secret`]}>
      <Routes>
        <Route path="/camera/:sessionCode" element={<CameraSenderPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

function renderNoCode() {
  return render(
    <MemoryRouter initialEntries={[`/camera`]}>
      <Routes>
        <Route path="/camera" element={<CameraSenderPage />} />
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
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('paramCode が無ければ、参加フォームは通信の確認を待たずに即時に出る', () => {
    // fetch / ws-ticket を一切解決させなくてもフォームが出ることを固定する。
    wsUrlMock.mockReturnValue(new Promise<string>(() => {}))
    renderNoCode()
    expect(screen.getByText(i18n.t('camera_sender.join_code_label'))).toBeTruthy()
    expect(screen.getByText(i18n.t('camera_sender.join_password_label'))).toBeTruthy()
  })

  it('connecting が 5 秒を超えたら「時間がかかっています」の案内を出す', async () => {
    vi.useFakeTimers()
    // ws-ticket を永遠に保留 → connecting のままにする。
    wsUrlMock.mockReturnValue(new Promise<string>(() => {}))
    renderWithCode()
    // join の await (microtask) を消化しつつ 5 秒進める。
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_100)
    })
    expect(screen.getByText(i18n.t('camera_sender.slow_connect_hint'))).toBeTruthy()
  })

  it('通信エラーで error に落ちたら、次の手 (パスワード確認先・電波・再試行) を出す', async () => {
    vi.useFakeTimers()
    // status の無いエラー = 通信断。有限回の自動再接続を使い切って error へ。
    wsUrlMock.mockRejectedValue(new Error('network down'))
    renderWithCode()
    // join → connectWs → reconnect を MAX_RECONNECT(10) 回×5秒分進める。
    await act(async () => {
      await vi.advanceTimersByTimeAsync(70_000)
    })
    expect(screen.getByText(i18n.t('camera_sender.error_next_steps_title'))).toBeTruthy()
    expect(screen.getByText(i18n.t('camera_sender.error_step_password'))).toBeTruthy()
    expect(screen.getByText(i18n.t('camera_sender.error_step_wifi'))).toBeTruthy()
    expect(screen.getByText(i18n.t('camera_sender.error_step_retry'))).toBeTruthy()
  })
})

describe('loading guidance: dictionary + source invariants', () => {
  it('新しい案内キーが ja・en 両方にあり非空である', () => {
    for (const dict of [ja, en] as Array<Record<string, unknown>>) {
      const cs = (dict.camera_sender ?? {}) as Record<string, unknown>
      for (const k of ['slow_connect_hint', 'error_next_steps_title', 'error_step_password', 'error_step_wifi', 'error_step_retry']) {
        expect(typeof cs[k]).toBe('string')
        expect((cs[k] as string).length).toBeGreaterThan(0)
      }
    }
  })

  const src = readFileSync(resolve(__dirname, '..', 'CameraSenderPage.tsx'), 'utf-8')

  it('5 秒超の案内は connecting の間だけ slowConnect で制御される', () => {
    expect(src).toContain('slowConnect')
    expect(src).toContain('setSlowConnect')
    expect(src).toContain('camera_sender.slow_connect_hint')
    expect(src).toContain('5_000')
  })

  it('error 画面に次の手の案内がある', () => {
    expect(src).toContain('camera_sender.error_next_steps_title')
    expect(src).toContain('camera_sender.error_step_password')
    expect(src).toContain('camera_sender.error_step_wifi')
    expect(src).toContain('camera_sender.error_step_retry')
  })

  it('先行の承認フローのガードを壊していない', () => {
    expect(src).toContain('approvalErrorCode')
    expect(src).toContain('device_not_approved')
    expect(src).toContain("setSenderState('waiting_approval')")
    expect(src).toContain('showWifiHint')
  })
})
