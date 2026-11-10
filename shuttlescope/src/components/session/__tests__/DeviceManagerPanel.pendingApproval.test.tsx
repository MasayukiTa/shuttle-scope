/**
 * operator-pending: WebSocket が未接続でも GET /sessions/{code}/devices が
 * approval_status=pending を返すとき、記録画面の「接続デバイス管理」に
 * 承認待ちの端末が必ず一覧に出て、承認/拒否ボタンが描画されることを
 * 実コンポーネントを描画して確かめる（写しだけのテストにしない）。
 *
 * 症状 (2026-11-10 19:41 本番): iPhone が pending で登録されたが
 * DeviceManagerPanel は device_list_update (WS) だけに頼っていたため
 * 「接続中のデバイスはありません」のままで承認ボタンが出なかった。
 * 修正後は WS 未接続でも REST 一覧から pending を拾い、承認枠を出す。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import type { SessionParticipant } from '@/types'

// 依存のモック
const apiGet = vi.fn()
vi.mock('@/api/client', () => ({
  apiGet: (...a: unknown[]) => apiGet(...a),
  apiPost: vi.fn().mockResolvedValue({ success: true }),
  apiDelete: vi.fn().mockResolvedValue({ success: true }),
  newIdempotencyKey: () => 'test-key',
}))

// useCameraHub: WS 未接続 (wsConnected=false, reconnecting=false)。
// これが「シグナリング: 未接続」の状態。
vi.mock('@/hooks/session/useCameraHub', () => ({
  useCameraHub: () => ({
    streams: [],
    wsConnected: false,
    reconnecting: false,
    reconnectCount: 0,
    connectionStates: {},
    iceGatheringStates: {},
    deviceNames: {},
    turnInUse: null,
    connect: vi.fn(),
    requestCamera: vi.fn(),
    sendMessage: vi.fn(),
  }),
}))

vi.mock('@/hooks/useRealtimeYolo', () => ({
  useRealtimeYolo: () => ({ detections: [], enabled: false }),
}))

// 重い子コンポーネントは描画だけ軽くする（本テストの関心外）。
vi.mock('../LiveSourceSelector', () => ({ LiveSourceSelector: () => null }))
vi.mock('../LiveInferenceOverlay', () => ({ LiveInferenceOverlay: () => null }))
vi.mock('../RealtimeYoloOverlay', () => ({ RealtimeYoloOverlay: () => null }))

import { DeviceManagerPanel } from '../DeviceManagerPanel'

function participant(over: Partial<SessionParticipant> = {}): SessionParticipant {
  return {
    id: 558,
    session_id: 1,
    role: 'camera',
    device_name: 'iPhone',
    device_type: 'iphone',
    connection_role: 'camera_candidate',
    source_capability: 'camera',
    video_receive_enabled: false,
    authenticated_at: null,
    connection_state: 'idle',
    joined_at: '2026-11-10T19:41:00Z',
    last_seen_at: '2026-11-10T19:41:00Z',
    is_connected: false,
    approval_status: 'pending',
    last_heartbeat: null,
    viewer_permission: 'default',
    device_class: 'phone',
    display_size_class: 'phone',
    ...over,
  }
}

beforeEach(() => {
  apiGet.mockReset()
  // navigator.mediaDevices が jsdom に無いため enumerateLocalCameras が
  // 落ちないように最小 stub。
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { enumerateDevices: vi.fn().mockResolvedValue([]) },
  })
})

describe('DeviceManagerPanel — WS 未接続でも pending を承認枠に出す', () => {
  it('GET /devices が pending を返すと、承認枠と承認/拒否ボタンが描画される', async () => {
    apiGet.mockResolvedValue({ success: true, data: [participant()] })

    render(<DeviceManagerPanel sessionCode="82NUQD" onClose={() => {}} />)

    await waitFor(() => expect(apiGet).toHaveBeenCalledWith('/sessions/82NUQD/devices'))

    const box = await screen.findByTestId('pending-approval-box')
    expect(box).toBeInTheDocument()
    expect(box).toHaveTextContent('iPhone')
    expect(screen.getByTestId('approve-btn')).toBeInTheDocument()
    expect(screen.getByTestId('reject-btn')).toBeInTheDocument()
    expect(screen.getByTestId('approve-btn')).toHaveTextContent('承認')
    expect(screen.getByTestId('reject-btn')).toHaveTextContent('拒否')
  })

  it('WS 未接続かつ pending ありのとき、シグナリング未接続の原因（入場券拒否）を 1 行で出す', async () => {
    apiGet.mockResolvedValue({ success: true, data: [participant()] })

    render(<DeviceManagerPanel sessionCode="82NUQD" onClose={() => {}} />)

    const cause = await screen.findByTestId('signal-cause')
    expect(cause).toBeInTheDocument()
    expect(cause).toHaveTextContent('入場券')
  })
})
