/**
 * 所有者不明 (unowned) の退避ラリーの件数と、明示操作 (自分のものとして送信 / 破棄)。
 *
 * 設計の根拠は utils/offlineStrokeQueue.ts の「所有者不明 (unowned) の退避」を参照。
 * ここは自動では何も送らない。呼ばれるのは、利用者が確認ダイアログで確定した時だけ。
 */
import { useCallback, useEffect, useState } from 'react'

import {
  claimUnownedForMatch,
  discardUnownedForMatch,
  listUnownedForMatch,
} from '@/utils/offlineStrokeQueue'

export function useUnownedRallies(matchId: number | null, userId: number | null) {
  const [count, setCount] = useState(0)

  const refresh = useCallback(async () => {
    if (matchId == null) {
      setCount(0)
      return
    }
    setCount((await listUnownedForMatch(matchId)).length)
  }, [matchId])

  useEffect(() => {
    void refresh()
  }, [refresh, userId])

  /** 確認済みの利用者 (userId) のものとして通常の退避キューへ移す。移した件数を返す。 */
  const claim = useCallback(async (): Promise<number> => {
    if (matchId == null || userId == null) return 0
    const moved = await claimUnownedForMatch(matchId, userId)
    await refresh()
    return moved
  }, [matchId, userId, refresh])

  const discard = useCallback(async (): Promise<number> => {
    if (matchId == null) return 0
    const n = await discardUnownedForMatch(matchId)
    await refresh()
    return n
  }, [matchId, refresh])

  return { count, refresh, claim, discard }
}
