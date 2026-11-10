/**
 * \u5fa9\u5143\u30c0\u30a4\u30a2\u30ed\u30b0\u4e2d\u306e\u81ea\u52d5\u518d\u9001\u4fdd\u7559 (muse \u5b9f\u6a5f 13:08):
 *   \u300c\u524d\u56de\u306e\u672a\u4fdd\u5b58\u30c7\u30fc\u30bf\u3092\u5fa9\u5143\u300d\u30c0\u30a4\u30a2\u30ed\u30b0\u304c\u51fa\u3066\u3044\u308b\u9593\u3001\u305d\u306e\n *   (match/set/rally) \u306e owned \u884c\u306f online \u5fa9\u5e30\u3067\u81ea\u52d5\u518d\u9001\u3055\u308c\u306a\u3044 (\u4fdd\u5b58\u5931\u6557\u3092\u51fa\u3055\u306a\u3044)\u3002
 *   \u5fa9\u5143 / \u7834\u68c4\u3067 release \u3057\u305f\u3089\u3001\u6b21\u56de sync \u3067 1 \u56de\u3060\u3051\u9001\u3089\u308c\u308b\u3002
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { IDBFactory } from 'fake-indexeddb'

const apiPost = vi.fn()
vi.mock('@/api/client', () => ({ apiPost: (...a: unknown[]) => apiPost(...a) }))

import { useOfflineSync } from '@/hooks/useOfflineSync'
import {
  holdResendForRally,
  releaseResendForRally,
  stashPending,
} from '@/utils/offlineStrokeQueue'
import { useAnnotationStore } from '@/store/annotationStore'

const USER = 42
const MATCH = 7

beforeEach(() => {
  globalThis.indexedDB = new IDBFactory()
  apiPost.mockReset()
  apiPost.mockResolvedValue({ success: true, data: { rally_id: 1, stroke_count: 1 } })
  // online \u6271\u3044\u306b\u3059\u308b (sync \u304c\u901a\u5e38\u306e\u9001\u4fe1\u30eb\u30fc\u30d7\u306b\u5165\u308b)\u3002
  Object.defineProperty(navigator, 'onLine', { value: true, configurable: true })
  useAnnotationStore.getState().clearSaveErrors()
})

afterEach(() => {
  globalThis.indexedDB = new IDBFactory()
  vi.restoreAllMocks()
})

describe('useOfflineSync resend hold during restore dialog', () => {
  it('\u5fa9\u5143\u30c0\u30a4\u30a2\u30ed\u30b0\u4e2d\u306e (set/rally) \u306f\u518d\u9001\u3055\u308c\u305a\u3001\u4fdd\u5b58\u5931\u6557\u3082\u51fa\u306a\u3044', async () => {
    await stashPending({ ownerUserId: USER, matchId: MATCH, setId: 1, rallyNum: 3, payload: { s: 1 }, queued_at: '2026-11-09T00:00:00Z' })
    holdResendForRally(MATCH, 1, 3)

    renderHook(() => useOfflineSync(MATCH, USER))

    // \u8d77\u52d5\u6642 sync \u304c\u6d41\u308c\u3001\u672a\u9001\u4fe1\u4ef6\u6570\u304c store \u306b\u53cd\u6620\u3055\u308c\u308b\u307e\u3067\u5f85\u3064\u3002
    await waitFor(() => expect(useAnnotationStore.getState().unsentCount).toBe(1))
    // \u4fdd\u7559\u4e2d\u306a\u306e\u3067 /strokes/batch \u306f\u547c\u3070\u308c\u306a\u3044\u3002
    expect(apiPost).not.toHaveBeenCalled()
    // \u5931\u6557\u6271\u3044\u3055\u308c\u3066\u3044\u306a\u3044 (\u8d64\u3044\u300c\u4fdd\u5b58\u5931\u6557\u300d\u304c\u51fa\u306a\u3044)\u3002
    expect(useAnnotationStore.getState().saveErrors).toHaveLength(0)
  })

  it('release \u5f8c\u306f\u6b21\u306e sync \u3067 1 \u56de\u3060\u3051\u9001\u3089\u308c\u308b', async () => {
    await stashPending({ ownerUserId: USER, matchId: MATCH, setId: 1, rallyNum: 3, payload: { s: 1 }, queued_at: '2026-11-09T00:00:00Z' })
    holdResendForRally(MATCH, 1, 3)

    renderHook(() => useOfflineSync(MATCH, USER))
    await waitFor(() => expect(useAnnotationStore.getState().unsentCount).toBe(1))
    expect(apiPost).not.toHaveBeenCalled()

    // \u5fa9\u5143 / \u7834\u68c4\u304c\u6c7a\u307e\u3063\u305f: \u4fdd\u7559\u3092\u89e3\u304f\u3002online \u30a4\u30d9\u30f3\u30c8\u3067 sync \u3092\u518d\u8d77\u52d5\u3002
    releaseResendForRally(MATCH, 1, 3)
    window.dispatchEvent(new Event('online'))

    // 1 \u56de\u3060\u3051\u9001\u3089\u308c\u3001\u5b89\u5b9a\u51aa\u7b49\u30ad\u30fc\u304c\u4ed8\u304f\u3002
    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(1))
    const [path, , headers] = apiPost.mock.calls[0]
    expect(path).toBe('/strokes/batch')
    expect((headers as Record<string, string>)['X-Idempotency-Key']).toBe('offline-42-7-1-3')
    // \u9001\u4fe1\u6210\u529f\u3067\u672a\u9001\u4fe1\u304c 0 \u306b\u306a\u308b\u3002
    await waitFor(() => expect(useAnnotationStore.getState().unsentCount).toBe(0))
    expect(useAnnotationStore.getState().saveErrors).toHaveLength(0)
  })
})
