/**
 * draft/ 行（入力中・ラリー未確定）の snapshot だけで payload が無い行が、
 * 自動再送（useOfflineSync）の送信対象に混入すると、body 空の POST /strokes/batch
 * が 422 を返し、ラリーが延々と保存失敗する（実機: pending_rallies の draft/2/6/15/29）。
 *
 * 正しい挙動:
 *   - payload の無い draft 行は送信対象から外す（IndexedDB には残す。確定時に
 *     AnnotatorPage が owned 枠へ payload 付きで送る）。未確定ラリーは winner/score を
 *     持たないため snapshot からは本文を組めず、サーバーには送れない。
 *   - payload 付きの owned 行だけが本文付きで /strokes/batch に送られる。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { IDBFactory } from 'fake-indexeddb'

const apiPost = vi.fn()
vi.mock('@/api/client', () => ({ apiPost: (...a: unknown[]) => apiPost(...a) }))

import { useOfflineSync } from '@/hooks/useOfflineSync'
import {
  listPendingForMatch,
  stashDraftRally,
  stashPending,
} from '@/utils/offlineStrokeQueue'
import { useAnnotationStore } from '@/store/annotationStore'

const USER = 42
const MATCH = 7

beforeEach(() => {
  globalThis.indexedDB = new IDBFactory()
  apiPost.mockReset()
  apiPost.mockResolvedValue({ success: true, data: { rally_id: 1, stroke_count: 1 } })
  Object.defineProperty(navigator, 'onLine', { value: true, configurable: true })
  useAnnotationStore.getState().clearSaveErrors()
})

afterEach(() => {
  globalThis.indexedDB = new IDBFactory()
  vi.restoreAllMocks()
})

describe('useOfflineSync skips payloadless draft rows', () => {
  it('draft 行（payload なし・snapshot あり）は送らず、payload 付き owned 行だけ本文付きで送る', async () => {
    // 入力中の下書き（payload を持たない。snapshot のみ）。
    await stashDraftRally({
      ownerUserId: USER,
      matchId: MATCH,
      setId: 2,
      rallyNum: 6,
      snapshot: { setId: 2, rallyNum: 6, strokes: [], inputStep: 1 },
      updated_at: '2026-11-09T00:00:00Z',
    })
    // 確定済みの owned 行（本文 payload を持つ）。
    await stashPending({
      ownerUserId: USER,
      matchId: MATCH,
      setId: 2,
      rallyNum: 7,
      payload: { rally: { set_id: 2, rally_num: 7 }, strokes: [{ stroke_num: 1 }] },
      queued_at: '2026-11-09T00:00:01Z',
    })

    renderHook(() => useOfflineSync(MATCH, USER))

    // payload 付き owned 行だけが 1 回だけ送られる（draft 行は送られない）。
    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(1))
    const [path, body, headers] = apiPost.mock.calls[0]
    expect(path).toBe('/strokes/batch')
    // 本文付きで出ている（body 空でない）。
    expect(body).toBeTruthy()
    expect(body).toEqual({ rally: { set_id: 2, rally_num: 7 }, strokes: [{ stroke_num: 1 }] })
    expect((headers as Record<string, string>)['X-Idempotency-Key']).toBe('offline-42-7-2-7')

    // draft 行の送信（空本文）は一度も起きていない。
    const emptyBodySends = apiPost.mock.calls.filter(
      ([, b]) => b === undefined || b === null,
    )
    expect(emptyBodySends).toHaveLength(0)

    // 空本文 422 由来の「保存失敗」も出ない。
    expect(useAnnotationStore.getState().saveErrors).toHaveLength(0)

    // draft 行は送信対象（listPendingForMatch）に入らない = IndexedDB に残る。
    const sendable = await listPendingForMatch(MATCH, USER)
    expect(sendable.map((r) => r.rallyNum)).toEqual([7])
  })

  it('owned 行が無く draft 行だけなら、何も送らない', async () => {
    await stashDraftRally({
      ownerUserId: USER,
      matchId: MATCH,
      setId: 15,
      rallyNum: 29,
      snapshot: { setId: 15, rallyNum: 29, strokes: [] },
      updated_at: '2026-11-09T00:00:00Z',
    })

    renderHook(() => useOfflineSync(MATCH, USER))

    // 送信対象は空。/strokes/batch は呼ばれない。
    const sendable = await listPendingForMatch(MATCH, USER)
    expect(sendable).toHaveLength(0)
    await waitFor(() => expect(apiPost).not.toHaveBeenCalled())
    expect(useAnnotationStore.getState().saveErrors).toHaveLength(0)
  })
})
