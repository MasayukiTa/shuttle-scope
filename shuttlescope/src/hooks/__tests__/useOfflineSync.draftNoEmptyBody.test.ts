/**
 * 回帰: useOfflineSync 本体は、payload を持たない draft/ 行を
 * /strokes/batch へ本文空で送らない (muse 実機: draft/2/6/15/29 の 422)。
 *
 * 背景:
 *   IndexedDB shuttlescope_offline / pending_rallies には、owned な確定ラリー
 *   (payload あり) と、入力途中の draft/ 行 (snapshot だけで payload が無い) が
 *   同じ ObjectStore に別 prefix で入る。遮断→復帰直後にラリーを終了したとき、
 *   draft/ 行が所有権フィルタを素通りして it.payload (=undefined) のまま送られると、
 *   POST /strokes/batch の本文が空になり 422 でラリーが保存されない (データ損失)。
 *
 * 既存の offlineStrokeQueue.draftSkip.test.ts は listPendingForMatch と手製の
 * ミニ送信ループで同じ不変条件を検証しているが、本テストは **useOfflineSync
 * フック本体** (起動時 sync とポーリングの実送信ループ、二重防御の payload==null
 * スキップと draft snapshot 経路) を renderHook で通し、end-to-end で:
 *   - 未確定 draft 行だけがあるとき apiPost('/strokes/batch', ...) が一度も呼ばれない
 *     (本文空 POST を出さない)。保存失敗 (saveErrors) も出ない。
 *   - 確定済み snapshot の draft 行は buildBatchPayload で本文を組み立てて送られ、
 *     送信成功でキューから消える。
 *   - payload を持つ owned 確定行は本文付きで送られる。
 * ことを保証する。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { IDBFactory } from 'fake-indexeddb'

const apiPost = vi.fn()
vi.mock('@/api/client', () => ({ apiPost: (...a: unknown[]) => apiPost(...a) }))

import { useOfflineSync } from '@/hooks/useOfflineSync'
import {
  listDraftsForMatch,
  listPendingForMatch,
  stashDraftRally,
  stashPending,
} from '@/utils/offlineStrokeQueue'
import { useAnnotationStore } from '@/store/annotationStore'

const USER = 2
const MATCH = 6
const SET = 15

beforeEach(() => {
  globalThis.indexedDB = new IDBFactory()
  apiPost.mockReset()
  apiPost.mockResolvedValue({ success: true, data: { rally_id: 1, stroke_count: 1 } })
  // online 扱いにする (sync が通常の送信ループに入る)。
  Object.defineProperty(navigator, 'onLine', { value: true, configurable: true })
  useAnnotationStore.getState().clearSaveErrors()
})

afterEach(() => {
  globalThis.indexedDB = new IDBFactory()
  vi.restoreAllMocks()
})

/** 入力途中 (未確定) snapshot: winner が無く、送れない。 */
function draftSnapshot() {
  return {
    setId: SET,
    rallyNum: 29,
    strokes: [{ stroke_num: 1, player: 'player_a', shot_type: 'clear', is_backhand: false, is_around_head: false }],
    pendingStroke: {},
    inputStep: 'shot_type',
    rallyStartTimestamp: 1.5,
    currentPlayer: 'player_a',
  }
}

/** 確定済み snapshot: winner / endType / スコアが揃う。 */
function confirmedSnapshot() {
  return {
    setId: SET,
    rallyNum: 29,
    strokes: [{ stroke_num: 1, player: 'player_a', shot_type: 'clear', is_backhand: false, is_around_head: false }],
    winner: 'player_a' as const,
    endType: 'ace',
    scoreAAfter: 11,
    scoreBAfter: 9,
    rallyStartTimestamp: 1.5,
    isBasicMode: true,
  }
}

describe('useOfflineSync は draft 行を本文空で送らない (draft/2/6/15/29 422 回帰)', () => {
  it('未確定 draft 行だけ: /strokes/batch は呼ばれず、保存失敗も出ない', async () => {
    await stashDraftRally({
      ownerUserId: USER,
      matchId: MATCH,
      setId: SET,
      rallyNum: 29,
      snapshot: draftSnapshot(),
      updated_at: '2026-11-10T00:00:00Z',
    })

    renderHook(() => useOfflineSync(MATCH, USER))

    // 起動時 sync が流れ、未送信件数が store に反映されるまで待つ。
    // draft 行は確定ラリーの未送信としては数えられないので 0 件。
    await waitFor(() => {
      expect(useAnnotationStore.getState().unsentCount).toBe(0)
    })
    // 本文空 POST を出さない: /strokes/batch が一度も呼ばれない。
    expect(apiPost).not.toHaveBeenCalled()
    // 保存失敗 (赤い「保存失敗」) も出ない。
    expect(useAnnotationStore.getState().saveErrors).toHaveLength(0)
    // draft 行は送られず残る。
    const draftsStill = await listDraftsForMatch(MATCH, USER)
    expect(draftsStill.map((d) => d.rallyNum)).toEqual([29])
  })

  it('確定済み snapshot の draft 行: 本文付きで送られ、成功でキューから消える', async () => {
    await stashDraftRally({
      ownerUserId: USER,
      matchId: MATCH,
      setId: SET,
      rallyNum: 29,
      snapshot: confirmedSnapshot(),
      updated_at: '2026-11-10T00:00:00Z',
    })

    renderHook(() => useOfflineSync(MATCH, USER))

    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(1))
    const [path, body, headers] = apiPost.mock.calls[0]
    expect(path).toBe('/strokes/batch')
    // 本文は空でなく、確定ラリーの本文が組み立てられている。
    expect(body).not.toBeNull()
    expect(body).toMatchObject({ rally: { rally_num: 29, winner: 'player_a', end_type: 'ace' } })
    // 安定冪等キー (draft でも確定ラリーと同じ offline-<user>-<match>-<set>-<rally>)。
    expect((headers as Record<string, string>)['X-Idempotency-Key']).toBe('offline-2-6-15-29')
    // 送信成功で draft 行が消える。
    await waitFor(async () => {
      expect(await listDraftsForMatch(MATCH, USER)).toHaveLength(0)
    })
    expect(useAnnotationStore.getState().saveErrors).toHaveLength(0)
  })

  it('payload を持つ owned 確定行は本文付きで送られる', async () => {
    await stashPending({
      ownerUserId: USER,
      matchId: MATCH,
      setId: SET,
      rallyNum: 30,
      payload: { rally: { set_id: SET, rally_num: 30 }, strokes: [] },
      queued_at: '2026-11-10T00:00:00Z',
    })

    renderHook(() => useOfflineSync(MATCH, USER))

    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(1))
    const [path, body, headers] = apiPost.mock.calls[0]
    expect(path).toBe('/strokes/batch')
    expect(body).not.toBeNull()
    expect(body).toMatchObject({ rally: { rally_num: 30 } })
    expect((headers as Record<string, string>)['X-Idempotency-Key']).toBe('offline-2-6-15-30')
    await waitFor(async () => {
      expect(await listPendingForMatch(MATCH, USER)).toHaveLength(0)
    })
    expect(useAnnotationStore.getState().saveErrors).toHaveLength(0)
  })
})
