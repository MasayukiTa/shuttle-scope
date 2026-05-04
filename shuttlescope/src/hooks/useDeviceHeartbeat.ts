/**
 * デバイスハートビートフック
 * 30 秒ごとに POST /api/sessions/{code}/devices/{pid}/heartbeat を送信する。
 * CameraSenderPage など、デバイス側で使用する。
 *
 * ws #10 fix: 旧コードは server 側で device が削除された場合 (operator が remove
 * 操作) もエラーを catch & 無視していたため、device 側 UI は「接続中」と思い込み
 * 続けていた。404 / 410 を「server-side removed」とみなして onRemoved コールバック
 * を発火する。
 */
import { useEffect, useRef } from 'react'
import { apiPost } from '@/api/client'

const HEARTBEAT_INTERVAL_MS = 30_000

export function useDeviceHeartbeat(
  sessionCode: string | null,
  participantId: number | null,
  onRemoved?: () => void,
) {
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const removedRef = useRef(false)

  useEffect(() => {
    if (!sessionCode || !participantId) return
    removedRef.current = false

    const sendHeartbeat = async () => {
      try {
        await apiPost(`/sessions/${sessionCode}/devices/${participantId}/heartbeat`, {})
      } catch (err: unknown) {
        // 404 / 410 は server 側で削除された signal とみなして onRemoved 通知 + ループ停止
        const e = err as { status?: number; message?: string }
        const status = e?.status
        if ((status === 404 || status === 410) && !removedRef.current) {
          removedRef.current = true
          if (timerRef.current) {
            clearInterval(timerRef.current)
            timerRef.current = null
          }
          if (onRemoved) onRemoved()
          return
        }
        // それ以外 (ネットワーク瞬断 etc) は次回で回復
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
  }, [sessionCode, participantId, onRemoved])
}
