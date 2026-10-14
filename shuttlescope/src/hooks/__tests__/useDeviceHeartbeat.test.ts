/**
 * useDeviceHeartbeat: サーバが参加者を失効させたと判断できる応答で onRemoved を呼ぶ。
 * バックエンドは列挙防止のため、トークン付きの削除済み参加者 / 終了済みセッションを
 * 404/410 ではなく汎用 401 で返す。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'

const apiPost = vi.fn()
vi.mock('@/api/client', () => ({ apiPost: (...a: unknown[]) => apiPost(...a) }))

import { useDeviceHeartbeat } from '@/hooks/useDeviceHeartbeat'

function statusError(status: number): Error & { status: number } {
  return Object.assign(new Error('x'), { status })
}

describe('useDeviceHeartbeat removal detection', () => {
  beforeEach(() => {
    apiPost.mockReset()
  })

  it('calls onRemoved on 401 when a participant token was sent', async () => {
    apiPost.mockRejectedValue(statusError(401))
    const onRemoved = vi.fn()
    renderHook(() => useDeviceHeartbeat('ABC', 7, onRemoved, 'tok'))
    await waitFor(() => expect(onRemoved).toHaveBeenCalledTimes(1))
  })

  it('does not treat 401 as removal when no participant token was sent', async () => {
    apiPost.mockRejectedValue(statusError(401))
    const onRemoved = vi.fn()
    renderHook(() => useDeviceHeartbeat('ABC', 7, onRemoved))
    await waitFor(() => expect(apiPost).toHaveBeenCalled())
    await Promise.resolve()
    expect(onRemoved).not.toHaveBeenCalled()
  })

  it.each([404, 410])('still calls onRemoved on %i (backward compatible)', async (status) => {
    apiPost.mockRejectedValue(statusError(status))
    const onRemoved = vi.fn()
    renderHook(() => useDeviceHeartbeat('ABC', 7, onRemoved, 'tok'))
    await waitFor(() => expect(onRemoved).toHaveBeenCalledTimes(1))
  })

  it('ignores transient errors (500)', async () => {
    apiPost.mockRejectedValue(statusError(500))
    const onRemoved = vi.fn()
    renderHook(() => useDeviceHeartbeat('ABC', 7, onRemoved, 'tok'))
    await waitFor(() => expect(apiPost).toHaveBeenCalled())
    await Promise.resolve()
    expect(onRemoved).not.toHaveBeenCalled()
  })
})
