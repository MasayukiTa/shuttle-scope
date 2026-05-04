/**
 * デバイスハートビートフック
 * 30 秒ごとに POST /api/sessions/{code}/devices/{pid}/heartbeat を送信する。
 * CameraSenderPage など、デバイス側で使用する。
 */
import { useEffect, useRef } from 'react'
import { apiPost } from '@/api/client'

const HEARTBEAT_INTERVAL_MS = 30_000

export function useDeviceHeartbeat(
  sessionCode: string | null,
  participantId: number | null,
) {
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    if (!sessionCode || !participantId) return

    const sendHeartbeat = async () => {
      try {
        await apiPost(`/sessions/${sessionCode}/devices/${participantId}/heartbeat`, {})
      } catch {
        // ハートビート失敗は無視（次回で回復）
      }
    }

    // 即時 1 回送信してからインターバル開始
    sendHeartbeat()
    timerRef.current = setInterval(sendHeartbeat, HEARTBEAT_INTERVAL_MS)

    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current)
        timerRef.current = null
      }
    }
  }, [sessionCode, participantId])
}
