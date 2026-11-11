/**
 * カメラ送信: 再読み込み後の再開 (#camera/<code> reload)。
 *
 * 症状 (2026-11-10 本番): iPhone の送信ページを再読み込みすると参加状態が消えて
 * パスワード入力画面に戻り、入れ直すと別の pending 参加者が増えていた。
 *
 * 直し方 (本テストが固定する不変条件):
 *   - 同一タブ (sessionStorage) に保存済みの参加者トークンがあれば、再読み込み後は
 *     パスワードを聞かずに保存済みトークンで再開する (?pwd= なしでも)。join 要求には
 *     participant_token が載る (device_uid と併せてサーバが同じ participant に合流)。
 *   - 保存済みトークンが無い再参加は承認を迂回せず、パスワードフォームへ案内する
 *     (新しい pending を正とする。トークンなしで承認状態を引き継がない)。
 *
 * 既存 viewer 側 (src/utils/participantRejoinToken.ts) と同じ sessionStorage の仕組み。
 * 実際に CameraSenderPage を描画して確かめる。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

import i18n from '@/i18n'
import { getDeviceUid } from '@/utils/deviceUid'
import { setParticipantRejoinToken } from '@/utils/participantRejoinToken'

// participantWsUrl の戻りで接続可否を制御する。既定は「接続成功」。
const wsUrlMock = vi.fn<() => Promise<string>>()
vi.mock('@/utils/cameraWs', () => ({
  participantWsUrl: (..._args: unknown[]) => wsUrlMock(),
}))

// heartbeat / 録画 は本テストの対象外。接続前後の分岐には関与しないので無害化する。
vi.mock('@/hooks/useDeviceHeartbeat', () => ({ useDeviceHeartbeat: () => {} }))
vi.mock('@/hooks/session/useServerSideRecording', () => ({
  useServerSideRecording: () => ({ state: 'idle', errorMsg: null, stop: vi.fn() }),
}))

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

const CODE = 'ABC123'

// join 要求のボディを捕まえるための記録先。
let lastJoinBody: Record<string, unknown> | null = null

function installFetch() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const u = String(url)
      if (u.includes('/join')) {
        lastJoinBody = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null
        return jsonResponse({
          success: true,
          data: {
            participant_id: 7,
            session_code: CODE,
            role: 'viewer',
            connection_role: 'device',
            participant_token: 'ptok-new',
          },
        })
      }
      return jsonResponse({ success: true, data: {} })
    }),
  )
}

function renderAt(search = '') {
  return render(
    <MemoryRouter initialEntries={[`/camera/${CODE}${search}`]}>
      <Routes>
        <Route path="/camera/:sessionCode" element={<CameraSenderPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('CameraSenderPage reload resume', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('ja')
    vi.stubGlobal('WebSocket', FakeWebSocket as unknown as typeof WebSocket)
    installFetch()
    wsUrlMock.mockReset()
    // テスト用モック値であり実接続ではない。既存の cameraWs.ts と同じ流儀で抑止する。
    // nosemgrep: javascript.lang.security.detect-insecure-websocket.detect-insecure-websocket
    wsUrlMock.mockResolvedValue('ws://test/ok')
    lastJoinBody = null
    try {
      sessionStorage.clear()
      localStorage.clear()
    } catch {
      /* noop */
    }
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('保存済みトークンがあれば ?pwd= なしの再読み込みでもパスワードを聞かずに再開し、join に participant_token を載せる', async () => {
    // 直前の参加で得たトークンを同一タブ (sessionStorage) に保存した状態を再現する。
    setParticipantRejoinToken(CODE, getDeviceUid(), 'ptok-saved')

    renderAt('') // ?pwd= なし = 素の再読み込み

    // join が走り participant_token が再提示されること。
    await waitFor(() => {
      expect(lastJoinBody).not.toBeNull()
    })
    expect(lastJoinBody?.participant_token).toBe('ptok-saved')
    expect(lastJoinBody?.session_password).toBeUndefined()

    // パスワード入力への誘導が出ていないこと (再開なのでフォームに戻さない)。
    expect(screen.queryByText(i18n.t('lan_session.join_password_required'))).toBeNull()
  })

  it('保存済みトークンが無い ?pwd= なしの再参加はパスワードフォームへ案内し、承認を迂回しない (join を送らない)', async () => {
    // sessionStorage は空 (beforeEach でクリア済み)。
    renderAt('') // ?pwd= なし

    await waitFor(() => {
      expect(screen.getByText(i18n.t('lan_session.join_password_required'))).toBeTruthy()
    })
    // トークンなしでは自動 join しない (新しい pending はユーザーの明示操作に委ねる)。
    expect(lastJoinBody).toBeNull()
  })
})
