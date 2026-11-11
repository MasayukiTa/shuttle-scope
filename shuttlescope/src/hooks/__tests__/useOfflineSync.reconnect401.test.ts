/**
 * fix/rally-end-after-reconnect (muse 実機 2026-11-10 18:05):
 *   通信騬断→復帰の直後にラリーを終了すると、復帰直後の
 *   認証更新 (refresh) がまだ解決しておらず POST /strokes/batch が 401 に
 *   なる。これは「認証更新中の一過性」であり、次回の online / ポーリングで
 *   refresh が ok になれば同じ安定冪等キーで再送すれば必ずサーバーへ届く。
 *
 *   旧実装は 401/403 を permanent (恒久拒否) と誤判定して再送を諸め、
 *   offline_sync_rejected の「保存失敗」を残したままにした (muse: 約 3 分後も残る)。
 *   修正後は 401/403 を再試行対象として扱い、次回の online で再送して成功させる。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { IDBFactory } from 'fake-indexeddb'

const apiPost = vi.fn()
vi.mock('@/api/client', () => ({ apiPost: (...a: unknown[]) => apiPost(...a) }))

import { useOfflineSync } from '@/hooks/useOfflineSync'
import { stashPending } from '@/utils/offlineStrokeQueue'
import { useAnnotationStore } from '@/store/annotationStore'

const USER = 42
const MATCH = 6

function httpError(status: number): Error {
  const err = new Error(`HTTP ${status}`) as Error & { status: number }
  err.status = status
  return err
}

beforeEach(() => {
  globalThis.indexedDB = new IDBFactory()
  apiPost.mockReset()
  Object.defineProperty(navigator, 'onLine', { value: true, configurable: true })
  useAnnotationStore.getState().clearSaveErrors()
})

afterEach(() => {
  globalThis.indexedDB = new IDBFactory()
  vi.restoreAllMocks()
})

describe('useOfflineSync: 401 right after reconnect is transient, not permanent', () => {
  it('does not mark a 401 as permanently rejected; resends on next online and succeeds', async () => {
    // 終了したラリー 29 が owned 枠に退避されている状態。
    await stashPending({
      ownerUserId: USER,
      matchId: MATCH,
      setId: 1,
      rallyNum: 29,
      payload: { rally: { rally_num: 29 } },
      queued_at: '2026-11-10T18:05:00Z',
    })

    // 1 回目の再送 (復帰直後): refresh がまだ ok でなく 401。
    // 2 回目以降 (次の online): refresh が解決して成功。
    apiPost
      .mockRejectedValueOnce(httpError(401))
      .mockResolvedValue({ success: true, data: { rally_id: 29, stroke_count: 1 } })

    renderHook(() => useOfflineSync(MATCH, USER))

    // 起動時 sync で 1 回目の送信が 401 になるまで待つ。
    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(1))

    // 一過性の 401 を「恒久拒否」として扱わない — offline_sync_rejected の
    // 保存失敗を残さない。
    expect(
      useAnnotationStore.getState().saveErrors.some((e) => e.rallyNum === 29),
    ).toBe(false)

    // 次の online で再送され、今度は refresh が ok なので成功する。
    window.dispatchEvent(new Event('online'))
    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(2))

    // 再送は同じ安定冪等キー (offline-42-6-1-29) を使う。
    for (const call of apiPost.mock.calls) {
      const headers = call[2] as Record<string, string> | undefined
      expect(headers?.['X-Idempotency-Key']).toBe('offline-42-6-1-29')
    }

    // 成功で未送信が 0 になり、保存失敗が残らない。
    await waitFor(() => expect(useAnnotationStore.getState().unsentCount).toBe(0))
    expect(useAnnotationStore.getState().saveErrors).toHaveLength(0)
  })
})
