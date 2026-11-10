/**
 * セッションの承認待ちデバイスを監視する（記録画面ヘッダーのバッジ用）。
 *
 * DeviceManagerPanel が閉じていてもヘッダーに「承認待ち N 台」を出すため、
 * パネルとは独立に GET /sessions/{code}/devices を 3 秒間隔で取得する。
 * - sessionCode が無いときは一切リクエストしない。
 * - WebSocket には依存しない（シグナリング未接続でも承認待ちを拾う）。
 * - 取得失敗時は直前の値を保持する（偽の 0 でバッジを消さない）。
 */
import { useEffect, useState, useCallback } from 'react'
import { apiGet } from '@/api/client'
import type { SessionParticipant } from '@/types'

export const PENDING_DEVICES_POLL_MS = 3_000

export interface SessionPendingDevices {
  pending: SessionParticipant[]
  count: number
}

export function useSessionPendingDevices(
  sessionCode: string | null | undefined,
): SessionPendingDevices {
  const [pending, setPending] = useState<SessionParticipant[]>([])

  const fetchPending = useCallback(async (code: string, alive: () => boolean) => {
    try {
      const res = await apiGet<{ success: boolean; data: SessionParticipant[] }>(
        `/sessions/${code}/devices`,
      )
      if (!alive()) return
      if (res.success && Array.isArray(res.data)) {
        setPending(res.data.filter((p) => p.approval_status === 'pending'))
      }
    } catch {
      // 失敗時は直前の値を保持（バッジを無言で消さない）。
    }
  }, [])

  useEffect(() => {
    if (!sessionCode) {
      setPending([])
      return
    }
    let alive = true
    const tick = () => fetchPending(sessionCode, () => alive)
    tick()
    const id = setInterval(tick, PENDING_DEVICES_POLL_MS)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [sessionCode, fetchPending])

  return { pending, count: pending.length }
}
