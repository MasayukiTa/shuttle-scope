/**
 * session-end: 「接続デバイス管理」(DeviceManagerPanel) の「セッションを終了」
 * ボタンが、確認ダイアログで OK のときに POST /sessions/{code}/end を
 * 呼び、onEnded を発火することを実コンポーネントを描画して確かめる。
 * キャンセル時は /end を呼ばないことも確かめる。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const apiPost = vi.fn()
vi.mock('@/api/client', () => ({
  apiGet: vi.fn().mockResolvedValue({ success: true, data: [] }),
  apiPost: (...a: unknown[]) => apiPost(...a),
  apiDelete: vi.fn().mockResolvedValue({ success: true }),
  newIdempotencyKey: () => 'test-key',
}))

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

vi.mock('../LiveSourceSelector', () => ({ LiveSourceSelector: () => null }))
vi.mock('../LiveInferenceOverlay', () => ({ LiveInferenceOverlay: () => null }))
vi.mock('../RealtimeYoloOverlay', () => ({ RealtimeYoloOverlay: () => null }))

import { DeviceManagerPanel } from '../DeviceManagerPanel'

beforeEach(() => {
  apiPost.mockReset()
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { enumerateDevices: vi.fn().mockResolvedValue([]) },
  })
})
afterEach(() => {
  vi.restoreAllMocks()
})

describe('DeviceManagerPanel end session', () => {
  it('calls POST /sessions/{code}/end and notifies onEnded when confirmed', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    apiPost.mockResolvedValueOnce({ success: true })
    const onEnded = vi.fn()

    render(<DeviceManagerPanel sessionCode="82NUQD" onClose={() => {}} onEnded={onEnded} />)

    fireEvent.click(screen.getByRole('button', { name: 'セッションを終了' }))

    await waitFor(() => expect(apiPost).toHaveBeenCalledWith('/sessions/82NUQD/end', {}))
    await waitFor(() => expect(onEnded).toHaveBeenCalledTimes(1))
  })

  it('does nothing when the confirm dialog is dismissed', () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    const onEnded = vi.fn()

    render(<DeviceManagerPanel sessionCode="82NUQD" onClose={() => {}} onEnded={onEnded} />)

    fireEvent.click(screen.getByRole('button', { name: 'セッションを終了' }))

    expect(apiPost).not.toHaveBeenCalledWith('/sessions/82NUQD/end', {})
    expect(onEnded).not.toHaveBeenCalled()
  })
})
