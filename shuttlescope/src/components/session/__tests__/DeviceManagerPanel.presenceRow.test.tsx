/**
 * presence-row (症状 c/d): PC 側『接続デバイス管理』の 1 行が、
 * WebSocket の接続有無 + ハートビート(30s TTL)から導いた 1 状態だけを
 * 表示することを、実コンポーネント(DeviceManagerPanel)を描画して確かめる。
 *
 * 症状 (2026-11-10 19:47 本番): スマホが切断・再読み込みしても PC 側が前の
 * iPhone を『承認済み・接続・送信中』のまま表示し続け、同じ行に『応答なし』が
 * 並んで状態が食い違っていた。修正後は、WS 未接続 or HB 失効なら行を『切断』と
 * 表示し、その行の『送信中』(connection_state=sending_video) は出さない
 * = 1 行 1 状態。
 *
 * computeDeviceConnected 単体の境界値は presence.test.tsx が担う。本テストは
 * 実際の行 DOM を描画して『切断表示』と『送信中抑制(1行1状態)』を確かめる。
 *
 * NOTE: fake timers は使わない。DeviceManagerPanel は fetchDevices を非同期に
 * 呼び、waitFor / findBy* が実タイマーで待つため、fake timers と衝突して
 * タイムアウトする。last_heartbeat は Date.now() からの相対で作り、実時間で
 * 判定させる(経過数秒は TTL 30s に対して誤差の範囲)。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import type { SessionParticipant } from '@/types'

const apiGet = vi.fn()
vi.mock('@/api/client', () => ({
  apiGet: (...a: unknown[]) => apiGet(...a),
  apiPost: vi.fn().mockResolvedValue({ success: true }),
  apiDelete: vi.fn().mockResolvedValue({ success: true }),
  newIdempotencyKey: () => 'test-key',
}))

// wsConnected はテストごとに差し替える。既定は接続。
let mockWsConnected = true
vi.mock('@/hooks/session/useCameraHub', () => ({
  useCameraHub: () => ({
    streams: [],
    wsConnected: mockWsConnected,
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
vi.mock('../LiveSourceSelector', () => ({ LiveSourceSelector: () => null }))
vi.mock('../LiveInferenceOverlay', () => ({ LiveInferenceOverlay: () => null }))
vi.mock('../RealtimeYoloOverlay', () => ({ RealtimeYoloOverlay: () => null }))

import { DeviceManagerPanel } from '../DeviceManagerPanel'

// last_heartbeat は現在時刻からの相対で作る(実時間で TTL 判定させる)。
function hb(secondsAgo: number): string {
  return new Date(Date.now() - secondsAgo * 1000).toISOString()
}

// 承認済みのアクティブカメラ端末。sending_video を出す条件を満たす
// (approval_status=approved かつ connection_role=active_camera かつ
//  connection_state=sending_video)。presence は last_heartbeat で可変。
function activeCamera(over: Partial<SessionParticipant> = {}): SessionParticipant {
  return {
    id: 558,
    session_id: 1,
    role: 'camera',
    device_name: 'iPhone',
    device_type: 'iphone',
    connection_role: 'active_camera',
    source_capability: 'camera',
    video_receive_enabled: false,
    authenticated_at: null,
    connection_state: 'sending_video',
    joined_at: '2026-11-10T19:41:00Z',
    last_seen_at: '2026-11-10T19:41:00Z',
    is_connected: true,
    approval_status: 'approved',
    last_heartbeat: hb(5),
    viewer_permission: 'default',
    device_class: 'phone',
    display_size_class: 'phone',
    ...over,
  }
}

beforeEach(() => {
  apiGet.mockReset()
  mockWsConnected = true
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { enumerateDevices: vi.fn().mockResolvedValue([]) },
  })
})

async function renderWith(data: SessionParticipant[]) {
  apiGet.mockResolvedValue({ success: true, data })
  render(<DeviceManagerPanel sessionCode="82NUQD" onClose={() => {}} />)
  await waitFor(() => expect(apiGet).toHaveBeenCalledWith('/sessions/82NUQD/devices'))
  // fetchDevices の setState が反映され、行が描画されるまで待つ。
  await screen.findByText('iPhone')
}

describe('DeviceManagerPanel — PC 側の行プレゼンス (症状 c/d)', () => {
  it('WS 未接続なら、送信中だった端末でも行は「切断」になり「送信中」を出さない (1行1状態)', async () => {
    mockWsConnected = false
    await renderWith([activeCamera({ last_heartbeat: hb(1) })])

    // 行は「切断」を表示する
    expect(screen.getByText('切断')).toBeInTheDocument()
    // 食い違いの元だった「接続」「送信中」は出ない
    expect(screen.queryByText('接続')).not.toBeInTheDocument()
    expect(screen.queryByText('送信中')).not.toBeInTheDocument()
  })

  it('WS 接続でもハートビートが失効(31s)なら「切断」になり「送信中」を出さない', async () => {
    mockWsConnected = true
    await renderWith([activeCamera({ last_heartbeat: hb(31) })])

    expect(screen.getByText('切断')).toBeInTheDocument()
    expect(screen.queryByText('接続')).not.toBeInTheDocument()
    expect(screen.queryByText('送信中')).not.toBeInTheDocument()
  })

  it('WS 接続かつハートビートが新鮮なら「接続」と「送信中」を出す (抑制は切断時のみ)', async () => {
    mockWsConnected = true
    await renderWith([activeCamera({ last_heartbeat: hb(5) })])

    expect(screen.getByText('接続')).toBeInTheDocument()
    expect(screen.getByText('送信中')).toBeInTheDocument()
    expect(screen.queryByText('切断')).not.toBeInTheDocument()
  })
})
