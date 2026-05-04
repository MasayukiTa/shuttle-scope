/**
 * オフライン耐性: 起動時 + ネットワーク復帰時に未送信ラリーを再送する。
 *
 * Phase A 実装。AnnotatorPage マウント時に呼ぶ。
 *
 * 仕様:
 *   - 起動時に 1 回 sync
 *   - online イベントで sync
 *   - 30 秒ごとにも try (online イベントが発火しないケースの保険)
 *   - 失敗したら次回まで stash に残す（exponential backoff なし、シンプル）
 */
import { useEffect, useRef } from 'react'

import { apiPost } from '@/api/client'
import { listPendingForMatch, removePending } from '@/utils/offlineStrokeQueue'

const POLL_INTERVAL_MS = 30_000

interface BatchResult {
  success: boolean
  data?: { rally_id: number; stroke_count: number }
}

export function useOfflineSync(matchId: number | null): void {
  const inflightRef = useRef(false)

  useEffect(() => {
    if (matchId == null) return

    const sync = async () => {
      if (inflightRef.current) return
      if (typeof navigator !== 'undefined' && navigator.onLine === false) return
      inflightRef.current = true
      try {
        const items = await listPendingForMatch(matchId)
        for (const it of items) {
          try {
            const res = await apiPost<BatchResult>('/strokes/batch', it.payload)
            if (res?.success) {
              await removePending(it.matchId, it.setId, it.rallyNum)
            }
          } catch {
            // ネットワーク or サーバ拒否 → このイテレーション中断、次回 retry
            break
          }
        }
      } finally {
        inflightRef.current = false
      }
    }

    void sync()

    const onOnline = () => { void sync() }
    if (typeof window !== 'undefined') {
      window.addEventListener('online', onOnline)
    }
    const interval = setInterval(() => { void sync() }, POLL_INTERVAL_MS)

    return () => {
      if (typeof window !== 'undefined') {
        window.removeEventListener('online', onOnline)
      }
      clearInterval(interval)
    }
  }, [matchId])
}
