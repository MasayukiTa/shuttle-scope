/**
 * ライブ推論フック
 * video 要素のフレームを canvas に描画して base64 取得し、
 * POST /api/tracknet/live_frame_hint に送信してシャトル位置候補を返す。
 *
 * 使用例:
 *   const { candidate, inferring, toggle } = useLiveInference(videoRef, sessionCode)
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { apiPost } from '@/api/client'
import type { LiveInferenceCandidate } from '@/types'

const FRAME_INTERVAL_MS = 200  // 5fps

export function useLiveInference(
  videoRef: React.RefObject<HTMLVideoElement>,
  sessionCode: string | null,
  enabled: boolean = true,
) {
  const [candidate, setCandidate] = useState<LiveInferenceCandidate | null>(null)
  const [inferring, setInferring] = useState(false)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const captureAndSend = useCallback(async () => {
    if (!videoRef.current || !sessionCode || videoRef.current.readyState < 2) return

    // Canvas 初期化（初回のみ）
    if (!canvasRef.current) {
      canvasRef.current = document.createElement('canvas')
      canvasRef.current.width = 512
      canvasRef.current.height = 288
    }
    const ctx = canvasRef.current.getContext('2d')
    if (!ctx) return

    ctx.drawImage(videoRef.current, 0, 0, 512, 288)
    const frame_b64 = canvasRef.current.toDataURL('image/jpeg', 0.7)

    try {
      setInferring(true)
      const res = await apiPost<{ success: boolean; data: LiveInferenceCandidate }>(
        '/tracknet/live_frame_hint',
        {
          session_code: sessionCode,
          frame_b64,
          frame_width: 512,
          frame_height: 288,
          confidence_threshold: 0.5,
        },
      )
      if (res.success) {
        setCandidate(res.data)
      }
    } catch {
      // 推論失敗は無視
    } finally {
      setInferring(false)
    }
  }, [videoRef, sessionCode])

  useEffect(() => {
    if (!enabled || !sessionCode) {
      if (timerRef.current) {
        clearInterval(timerRef.current)
        timerRef.current = null
      }
      setCandidate(null)
      return
    }
    timerRef.current = setInterval(captureAndSend, FRAME_INTERVAL_MS)
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current)
        timerRef.current = null
      }
    }
  }, [enabled, sessionCode, captureAndSend])

  const reset = useCallback(() => setCandidate(null), [])

  return { candidate, inferring, reset }
}
