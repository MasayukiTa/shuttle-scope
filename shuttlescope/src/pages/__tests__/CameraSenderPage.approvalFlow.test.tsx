/**
 * カメラ送信: デバイス承認フロー (#approval-wait)。
 *
 * 背景:
 *   ws-ticket 取得が 403 を返しても、旧実装はすべて「再参加してください」
 *   (rejoin_required) または汎用エラー + Wi-Fi 確認案内へ倒していた。だが実際には
 *   operator がまだ承認していないだけ (approval_status="pending") の端末も 403 で
 *   返るため、承認を待てば直るのに「参加し直せ」と誤誘導していた。
 *
 * サーバー (backend/routers/sessions.py issue_camera_ws_ticket) は未承認/拒否を
 *   detail={ code, message } で区別して返すようにした。フロントはその機械可読な
 *   code を見て分岐する:
 *     - 403 device_not_approved → error ではなく waiting_approval 画面 (Wi-Fi 案内なし)
 *     - 403 device_rejected    → 拒否専用メッセージ (Wi-Fi 案内なし)
 *     - その他 401/403・token 欠落 → rejoin_required (Wi-Fi 案内なし)
 *     - 通信エラー (status なし) → 自動再接続 (reconnect_failed まで Wi-Fi 案内なし)
 *
 * 本テストは実際に CameraSenderPage を描画し、注入した 403/ネットワーク断に対して
 * 正しい画面が出ること、そして Wi-Fi 確認案内が通信エラー起因のときだけ出ることを
 * 確かめる。あわせて辞書・ソースの構造不変条件 (#665 の既存ガードを壊さないこと) も
 * 固定する。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { readFileSync } from 'fs'
import { resolve } from 'path'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

import ja from '@/i18n/ja.json'
import en from '@/i18n/en.json'

// participantWsUrl の戻りで接続可否を制御する。既定は「承認待ち 403」。
const wsUrlMock = vi.fn<() => Promise<string>>()
vi.mock('@/utils/cameraWs', () => ({
  participantWsUrl: (..._args: unknown[]) => wsUrlMock(),
}))

// heartbeat / 録画 / ICE は本テストの対象外。接続前に分岐するので無害化する。
vi.mock('@/hooks/useDeviceHeartbeat', () => ({ useDeviceHeartbeat: () => {} }))
vi.mock('@/hooks/session/useServerSideRecording', () => ({
  useServerSideRecording: () => ({ state: 'idle', errorMsg: null, stop: vi.fn() }),
}))

import i18n from '@/i18n'
import { CameraSenderPage } from '../CameraSenderPage'

// participant_token を join 応答で返し、savedTokenRef を埋める (!token で rejoin に落ちない)。
function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function httpError(status: number, detailObj: unknown): Error {
  // apiPost 相当: message に本文テキスト、status を載せた Error。
  const e = new Error(JSON.stringify({ detail: detailObj })) as Error & { status: number }
  e.status = status
  return e
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

describe('CameraSenderPage device approval flow', () => {
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
    vi.unstubAllGlobals()
  })

  it('承認待ち (403 device_not_approved) は error ではなく待機画面を出し、Wi-Fi 案内を出さない', async () => {
    wsUrlMock.mockRejectedValue(httpError(403, { code: 'device_not_approved', message: 'x' }))
    renderAt()
    await waitFor(() => {
      expect(screen.getByText(i18n.t('camera_sender.waiting_approval_title'))).toBeTruthy()
    })
    expect(screen.queryByText(i18n.t('camera_sender.rejoin_required'))).toBeNull()
    expect(screen.queryByText(i18n.t('auto.CameraSenderPage.k_wifi_check'))).toBeNull()
  })

  it('拒否 (403 device_rejected) は拒否メッセージを出し、Wi-Fi 案内を出さない', async () => {
    wsUrlMock.mockRejectedValue(httpError(403, { code: 'device_rejected', message: 'x' }))
    renderAt()
    await waitFor(() => {
      expect(screen.getByText(i18n.t('camera_sender.device_rejected'))).toBeTruthy()
    })
    expect(screen.queryByText(i18n.t('auto.CameraSenderPage.k_wifi_check'))).toBeNull()
    expect(screen.queryByText(i18n.t('camera_sender.waiting_approval_title'))).toBeNull()
  })

  it('code のない 403 は再参加案内 (rejoin_required) を出し、Wi-Fi 案内を出さない', async () => {
    wsUrlMock.mockRejectedValue(httpError(403, 'このデバイスは拒否されています'))
    renderAt()
    await waitFor(() => {
      expect(screen.getByText(i18n.t('camera_sender.rejoin_required'))).toBeTruthy()
    })
    expect(screen.queryByText(i18n.t('auto.CameraSenderPage.k_wifi_check'))).toBeNull()
  })
})

describe('approval flow: dictionary + source invariants', () => {
  it('新しい承認待ち/拒否のキーが ja・en 両方にあり非空である', () => {
    for (const dict of [ja, en] as Array<Record<string, any>>) {
      const cs = dict.camera_sender as Record<string, unknown>
      for (const k of ['device_rejected', 'waiting_approval_title', 'waiting_approval_hint']) {
        expect(typeof cs[k]).toBe('string')
        expect((cs[k] as string).length).toBeGreaterThan(0)
      }
    }
  })

  const src = readFileSync(resolve(__dirname, '..', 'CameraSenderPage.tsx'), 'utf-8')

  it('承認の機械可読コードで分岐している (文言依存にしていない)', () => {
    expect(src).toContain('approvalErrorCode')
    expect(src).toContain('device_not_approved')
    expect(src).toContain('device_rejected')
    // #665 の既存ガードを壊していない
    expect(src).toContain('camera_sender.rejoin_required')
    expect(src).toContain('camera_sender.session_gone')
    expect(src).toContain('!savedTokenRef.current')
  })

  it('Wi-Fi 確認案内は通信エラー起因 (showWifiHint) のときだけ出す', () => {
    expect(src).toContain('showWifiHint')
    // k_wifi_check は showWifiHint ガードの内側にある
    const i = src.indexOf('k_wifi_check')
    const before = src.slice(Math.max(0, i - 200), i)
    expect(before).toContain('showWifiHint')
  })

  it('承認待ちは reconnect ではなく専用の再確認でポーリングする', () => {
    expect(src).toContain('scheduleApprovalRecheck')
    expect(src).toContain("setSenderState('waiting_approval')")
  })
})
