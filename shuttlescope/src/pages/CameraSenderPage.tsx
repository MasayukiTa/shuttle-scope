/**
 * カメラ送信ページ — iOS / タブレット向け
 *
 * State 遷移:
 *   join → A（待機） → B（確認） → C（送信中）
 *
 * WebRTC フロー:
 *   1. POST /api/sessions/{code}/join → participant_id 取得
 *   2. /ws/camera/{code}?participant_id={id} WS 接続
 *   3. device_hello 送信 → State A
 *   4. camera_request 受信 → State B
 *   5. ユーザー承認 → getUserMedia(rear) → offer → State C
 *   6. webrtc_answer / ice_candidate 交換
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Camera, WifiOff, Loader2, CheckCircle2, XCircle } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { apiPost } from '@/api/client'

type SenderState = 'join' | 'connecting' | 'state_a' | 'state_b' | 'state_c' | 'error'

interface JoinForm {
  sessionCode: string
  password: string
  deviceName: string
}

function getDeviceType(): string {
  const ua = navigator.userAgent
  if (/iPad/.test(ua)) return 'ipad'
  if (/iPhone/.test(ua)) return 'iphone'
  return 'pc'
}

export function CameraSenderPage() {
  const { sessionCode: paramCode } = useParams<{ sessionCode: string }>()
  const { t } = useTranslation()

  const [senderState, setSenderState] = useState<SenderState>(paramCode ? 'connecting' : 'join')
  const [form, setForm] = useState<JoinForm>({
    sessionCode: paramCode ?? '',
    password: '',
    deviceName: '',
  })
  const [errorMsg, setErrorMsg] = useState('')
  const [participantId, setParticipantId] = useState<number | null>(null)

  const wsRef = useRef<WebSocket | null>(null)
  const pcRef = useRef<RTCPeerConnection | null>(null)
  const localStreamRef = useRef<MediaStream | null>(null)
  const previewRef = useRef<HTMLVideoElement>(null)

  // ─── セッション参加 ───────────────────────────────────────────────────────

  const joinSession = useCallback(async (code: string, password: string, deviceName: string) => {
    setSenderState('connecting')
    setErrorMsg('')
    try {
      const res = await apiPost<{ success: boolean; data: { participant_id: number; session_code: string; role: string; connection_role: string } }>(
        `/sessions/${code}/join`, {
          role: 'viewer',
          device_name: deviceName || `${getDeviceType()}-camera`,
          device_type: getDeviceType(),
          session_password: password || undefined,
        }
      )
      if (!res.success) throw new Error('join failed')
      const pid = res.data.participant_id
      setParticipantId(pid)
      connectWs(code, pid)
    } catch (err: any) {
      const status = err?.response?.status
      if (status === 401) {
        setErrorMsg(t('camera_sender.join_error_invalid'))
      } else {
        setErrorMsg(t('camera_sender.join_error_network'))
      }
      setSenderState('join')
    }
  }, [t])

  // URL からセッションコードが渡された場合は直接参加試行
  useEffect(() => {
    if (paramCode && senderState === 'connecting') {
      // パスワードなしで一旦試みる（パスワードなしセッションに対応）
      joinSession(paramCode, '', '')
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ─── WebSocket 接続 ───────────────────────────────────────────────────────

  const connectWs = useCallback((code: string, pid: number) => {
    const host = window.location.hostname
    const wsUrl = `ws://${host}:8765/ws/camera/${code}?participant_id=${pid}`
    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onopen = () => {
      ws.send(JSON.stringify({
        type: 'device_hello',
        participant_id: pid,
        device_name: form.deviceName || `${getDeviceType()}-camera`,
        device_type: getDeviceType(),
      }))
      setSenderState('state_a')
    }

    ws.onmessage = async (event) => {
      try {
        const msg = JSON.parse(event.data)
        if (msg.type === 'camera_request') {
          setSenderState('state_b')
        } else if (msg.type === 'webrtc_answer' && pcRef.current) {
          await pcRef.current.setRemoteDescription({ type: 'answer', sdp: msg.sdp })
        } else if (msg.type === 'ice_candidate' && pcRef.current) {
          await pcRef.current.addIceCandidate({
            candidate: msg.candidate,
            sdpMid: msg.sdp_mid,
            sdpMLineIndex: msg.sdp_m_line_index,
          }).catch(() => {})
        }
      } catch { /* ignore */ }
    }

    ws.onclose = () => {
      wsRef.current = null
      if (senderState === 'state_c' || senderState === 'state_a' || senderState === 'state_b') {
        setSenderState('error')
        setErrorMsg(t('camera_sender.join_error_network'))
      }
    }

    ws.onerror = () => {
      setSenderState('error')
      setErrorMsg(t('camera_sender.join_error_network'))
    }
  }, [form.deviceName, t, senderState])

  // ─── カメラ起動 & WebRTC offer ────────────────────────────────────────────

  const startCamera = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      })
      localStreamRef.current = stream
      if (previewRef.current) {
        previewRef.current.srcObject = stream
      }

      const pc = new RTCPeerConnection({ iceServers: [{ urls: 'stun:stun.l.google.com:19302' }] })
      pcRef.current = pc

      stream.getTracks().forEach((track) => pc.addTrack(track, stream))

      pc.onicecandidate = (e) => {
        if (e.candidate && wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({
            type: 'ice_candidate',
            participant_id: participantId,
            candidate: e.candidate.candidate,
            sdp_mid: e.candidate.sdpMid,
            sdp_m_line_index: e.candidate.sdpMLineIndex,
          }))
        }
      }

      const offer = await pc.createOffer()
      await pc.setLocalDescription(offer)

      wsRef.current?.send(JSON.stringify({
        type: 'camera_accept',
        participant_id: participantId,
      }))
      wsRef.current?.send(JSON.stringify({
        type: 'webrtc_offer',
        participant_id: participantId,
        sdp: offer.sdp,
      }))

      setSenderState('state_c')
    } catch {
      setErrorMsg('カメラの起動に失敗しました。カメラへのアクセスを許可してください。')
    }
  }, [participantId])

  // ─── 配信停止 ─────────────────────────────────────────────────────────────

  const stopCamera = useCallback(() => {
    localStreamRef.current?.getTracks().forEach((t) => t.stop())
    localStreamRef.current = null
    pcRef.current?.close()
    pcRef.current = null
    wsRef.current?.send(JSON.stringify({
      type: 'camera_stop',
      participant_id: participantId,
    }))
    setSenderState('state_a')
  }, [participantId])

  // アンマウント時クリーンアップ
  useEffect(() => {
    return () => {
      localStreamRef.current?.getTracks().forEach((t) => t.stop())
      pcRef.current?.close()
      wsRef.current?.close()
    }
  }, [])

  // ─── レンダリング ──────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-gray-900 text-white flex flex-col items-center justify-center p-4">
      {/* ロゴ */}
      <div className="mb-6 text-center">
        <div className="inline-flex items-center gap-2 text-blue-400 mb-1">
          <Camera size={24} />
          <span className="text-lg font-bold">ShuttleScope</span>
        </div>
        <p className="text-gray-400 text-sm">{t('camera_sender.join_title')}</p>
      </div>

      {/* ─── State: join ────────────────── */}
      {(senderState === 'join' || (senderState === 'connecting' && !paramCode)) && (
        <div className="w-full max-w-sm bg-gray-800 rounded-xl p-5 shadow-2xl">
          <div className="space-y-3">
            <div>
              <label className="block text-xs text-gray-400 mb-1">{t('camera_sender.join_code_label')}</label>
              <input
                type="text"
                value={form.sessionCode}
                onChange={(e) => setForm((f) => ({ ...f, sessionCode: e.target.value.toUpperCase() }))}
                placeholder="XXXXXX"
                className="w-full bg-gray-700 rounded-lg px-3 py-2 text-sm font-mono text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
                autoCapitalize="characters"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">{t('camera_sender.join_password_label')}</label>
              <input
                type="password"
                value={form.password}
                onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
                className="w-full bg-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">{t('camera_sender.join_device_label')}</label>
              <input
                type="text"
                value={form.deviceName}
                onChange={(e) => setForm((f) => ({ ...f, deviceName: e.target.value }))}
                placeholder="例: コートサイドiPhone"
                className="w-full bg-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            {errorMsg && (
              <div className="flex items-center gap-1.5 text-red-400 text-xs">
                <XCircle size={14} />
                {errorMsg}
              </div>
            )}
            <button
              onClick={() => joinSession(form.sessionCode, form.password, form.deviceName)}
              disabled={!form.sessionCode}
              className="w-full py-2.5 rounded-lg bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-sm font-medium"
            >
              {t('camera_sender.join_button')}
            </button>
          </div>
        </div>
      )}

      {/* ─── State: connecting ──────────── */}
      {senderState === 'connecting' && paramCode && (
        <div className="text-center">
          <Loader2 size={40} className="animate-spin text-blue-400 mx-auto mb-3" />
          <p className="text-gray-300 text-sm">{t('camera_sender.join_connecting')}</p>
        </div>
      )}

      {/* ─── State A: 待機 ──────────────── */}
      {senderState === 'state_a' && (
        <div className="w-full max-w-sm text-center">
          <div className="bg-gray-800 rounded-xl p-8 shadow-2xl">
            <div className="w-16 h-16 rounded-full bg-blue-900/50 flex items-center justify-center mx-auto mb-4">
              <Camera size={28} className="text-blue-400" />
            </div>
            <p className="text-lg font-semibold mb-2">{t('camera_sender.state_a_title')}</p>
            <p className="text-gray-400 text-sm">{t('camera_sender.state_a_hint')}</p>
            <div className="mt-4 flex items-center justify-center gap-1.5 text-green-400 text-xs">
              <CheckCircle2 size={14} />
              {t('camera_sender.status_connected')}
            </div>
          </div>
        </div>
      )}

      {/* ─── State B: 確認 ──────────────── */}
      {senderState === 'state_b' && (
        <div className="w-full max-w-sm">
          <div className="bg-gray-800 rounded-xl p-6 shadow-2xl border border-amber-500/40">
            <div className="w-16 h-16 rounded-full bg-amber-900/50 flex items-center justify-center mx-auto mb-4">
              <Camera size={28} className="text-amber-400" />
            </div>
            <p className="text-center text-lg font-semibold mb-5">{t('camera_sender.state_b_title')}</p>
            <div className="space-y-2">
              <button
                onClick={startCamera}
                className="w-full py-3 rounded-xl bg-red-600 hover:bg-red-500 text-white font-semibold flex items-center justify-center gap-2"
              >
                <Camera size={18} />
                {t('camera_sender.state_b_start')}
              </button>
              <button
                onClick={() => setSenderState('state_a')}
                className="w-full py-2.5 rounded-xl bg-gray-700 hover:bg-gray-600 text-gray-300 text-sm"
              >
                {t('camera_sender.state_b_cancel')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ─── State C: 送信中 ────────────── */}
      {senderState === 'state_c' && (
        <div className="w-full max-w-sm">
          {/* カメラプレビュー */}
          <div className="relative mb-4 rounded-xl overflow-hidden bg-black aspect-video">
            <video
              ref={previewRef}
              autoPlay
              playsInline
              muted
              className="w-full h-full object-cover"
            />
            <div className="absolute top-2 left-2 flex items-center gap-1.5 bg-red-600 text-white text-xs px-2 py-0.5 rounded-full">
              <span className="w-1.5 h-1.5 rounded-full bg-white animate-pulse" />
              {t('camera_sender.state_c_active')}
            </div>
          </div>
          <p className="text-center text-xs text-gray-400 mb-4">{t('camera_sender.state_c_hint')}</p>
          <button
            onClick={stopCamera}
            className="w-full py-3 rounded-xl bg-gray-700 hover:bg-gray-600 text-white font-medium flex items-center justify-center gap-2"
          >
            <VideoOff size={18} />
            {t('camera_sender.state_c_stop')}
          </button>
        </div>
      )}

      {/* ─── State: error ───────────────── */}
      {senderState === 'error' && (
        <div className="w-full max-w-sm text-center">
          <div className="bg-gray-800 rounded-xl p-6 shadow-2xl border border-red-500/40">
            <WifiOff size={36} className="text-red-400 mx-auto mb-3" />
            <p className="text-sm text-gray-300 mb-4">{errorMsg || t('camera_sender.join_error_network')}</p>
            <button
              onClick={() => setSenderState('join')}
              className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-sm"
            >
              もう一度試す
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
