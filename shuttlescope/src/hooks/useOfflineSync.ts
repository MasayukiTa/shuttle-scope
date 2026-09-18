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
            // apiPost は既定で**毎回新しい** idempotency key を作る。再送のたびに
            // キーが変わると、サーバが「処理済みだが応答を失った」最初の送信と
            // 同じものだと判定できず、ラリーが二重に入る。キューの同一性
            // (match/set/rally) から安定キーを作って上書きする。
            const stableKey = `offline-${it.matchId}-${it.setId}-${it.rallyNum}`
            const res = await apiPost<BatchResult>('/strokes/batch', it.payload, {
              'X-Idempotency-Key': stableKey,
            })
            if (res?.success) {
              await removePending(it.matchId, it.setId, it.rallyNum)
            }
          } catch (e) {
            // 旧実装は無条件 break だった。恒久的な 4xx (壊れたペイロード等) が
            // 1 件入ると、**その後ろのラリーが永久に送られない**まま無言で
            // 滞留する。再試行で直るもの (ネットワーク / 5xx / 429) だけ
            // 中断し、直らないものは捨てて先へ進む。
            const status = (e as { status?: number } | null)?.status
            const permanent =
              typeof status === 'number' &&
              status >= 400 && status < 500 &&
              status !== 408 && status !== 429
            if (permanent) {
              // 何度送っても通らない 1 件。**キューからは外さない** —
              // 注釈データを黙って捨てるのは、この機構が防ごうとしている
              // ことそのもの。後続を止めないために飛ばすだけにする。
              // (この件を操作者に見せる UI が無いのは別途の課題。
              //  今は「後続が全部止まる」ほうを先に止める)
              console.warn(
                `[offline-sync] rally ${it.setId}/${it.rallyNum} は ${status} で` +
                  ' 恒久的に拒否されています。後続を処理するため飛ばします。',
              )
              continue
            }
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
