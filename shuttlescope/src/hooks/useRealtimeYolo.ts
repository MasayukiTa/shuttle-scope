/**
 * ブラウザ中継リアルタイム YOLO フック
 *
 * 引数の MediaStream から OffscreenCanvas で定期キャプチャし、JPEG 化して
 * `/ws/yolo/realtime/{sessionCode}` へ送信。サーバから返る bbox を state 提供。
 *
 * - オペレーター PC のみで有効化（ViewerPage 等では使わない）
 * - enabled=false で全停止＆WebSocket クローズ
 * - バックエンド共有状態なしで複数 PC 並列動作可能
 */
import { useEffect, useRef, useState } from 'react'

export interface RealtimeBox {
  x1: number  // 正規化 [0,1]
  y1: number
  x2: number
  y2: number
  conf: number
}

export interface RealtimeYoloState {
  boxes: RealtimeBox[]
  inferMs: number | null
  connected: boolean
  error: string | null
}

const TARGET_FPS = 10
const JPEG_QUALITY = 0.55
const CAPTURE_W = 640
const CAPTURE_H = 360

export function useRealtimeYolo(
  stream: MediaStream | null,
  sessionCode: string | null,
  enabled: boolean,
): RealtimeYoloState {
  const [boxes, setBoxes] = useState<RealtimeBox[]>([])
  const [inferMs, setInferMs] = useState<number | null>(null)
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const wsRef = useRef<WebSocket | null>(null)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const inflightRef = useRef(0)

  useEffect(() => {
    if (!enabled || !stream || !sessionCode) {
      setBoxes([])
      setConnected(false)
      setError(null)
      return
    }

    // 隠し video 要素に stream を流して readyState を待つ
    const video = document.createElement('video')
    video.muted = true
    video.playsInline = true
    video.autoplay = true
    video.srcObject = stream
    videoRef.current = video

    const canvas = document.createElement('canvas')
    canvas.width = CAPTURE_W
    canvas.height = CAPTURE_H
    canvasRef.current = canvas
    const ctx = canvas.getContext('2d')

    // WS 接続 (Electron(file:) / LAN(http:) / Tunnel(https:) 分岐)
    const isElectron = window.location.protocol === 'file:'
    const isHttps = window.location.protocol === 'https:'
    const wsProto = isHttps ? 'wss' : 'ws'
    const wsHost = isElectron
      ? 'localhost:8765'
      : isHttps
        ? window.location.host
        : `${window.location.hostname || 'localhost'}:8765`
    const wsUrl = `${wsProto}://${wsHost}/ws/yolo/realtime/${encodeURIComponent(sessionCode)}`

    let ws: WebSocket
    try {
      ws = new WebSocket(wsUrl)
    } catch (e) {
      setError(`WebSocket 接続失敗: ${e}`)
      return
    }
    wsRef.current = ws
    ws.binaryType = 'arraybuffer'

    ws.onopen = () => {
      setConnected(true)
      setError(null)
      // ws #5 fix: reconnect 後 inflightRef が 1 のまま残ると新規キャプチャが
      // 抑止され続け FPS=0 のまま「connected」になる sealed-zero-FPS 状態に
      // なっていた。open 時に必ずリセットする。
      inflightRef.current = 0
    }
    ws.onclose = () => {
      setConnected(false)
      // ws #5 fix: close 時も明示的にリセット (次の reconnect で再増分されるため)
      inflightRef.current = 0
    }
    ws.onerror = () => {
      setError('WebSocket エラー')
      inflightRef.current = 0
    }
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data)
        if (msg.type === 'detections') {
          setBoxes(Array.isArray(msg.boxes) ? msg.boxes : [])
          if (typeof msg.infer_ms === 'number') setInferMs(msg.infer_ms)
          inflightRef.current = Math.max(0, inflightRef.current - 1)
        } else if (msg.type === 'skipped') {
          inflightRef.current = Math.max(0, inflightRef.current - 1)
        } else if (msg.type === 'error') {
          setError(msg.message ?? msg.reason ?? 'error')
          inflightRef.current = Math.max(0, inflightRef.current - 1)
        } else if (msg.type === 'ready') {
          setError(null)
        }
      } catch { /* ignore malformed */ }
    }

    // キャプチャループ
    const intervalMs = Math.round(1000 / TARGET_FPS)
    timerRef.current = setInterval(() => {
      if (!ctx || ws.readyState !== WebSocket.OPEN) return
      if (video.readyState < 2) return
      if (inflightRef.current >= 1) return  // 1 推論ごと同期
      try {
        ctx.drawImage(video, 0, 0, CAPTURE_W, CAPTURE_H)
      } catch { return }
      canvas.toBlob(
        (blob) => {
          if (!blob || ws.readyState !== WebSocket.OPEN) return
          blob.arrayBuffer().then((ab) => {
            if (ws.readyState === WebSocket.OPEN) {
              inflightRef.current += 1
              ws.send(ab)
            }
          }).catch(() => {})
        },
        'image/jpeg',
        JPEG_QUALITY,
      )
    }, intervalMs)

    return () => {
      if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
      try { ws.close() } catch { /* ignore */ }
      wsRef.current = null
      try { video.srcObject = null } catch { /* ignore */ }
      videoRef.current = null
      canvasRef.current = null
      inflightRef.current = 0
      setBoxes([])
      setConnected(false)
    }
  }, [enabled, stream, sessionCode])

  return { boxes, inferMs, connected, error }
}
