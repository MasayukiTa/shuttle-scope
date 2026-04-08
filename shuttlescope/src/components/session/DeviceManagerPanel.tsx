/**
 * デバイス管理パネル — PC オペレーター向けカメラ/デバイス制御 UI
 *
 * 機能:
 * - 接続デバイス一覧（GET /api/sessions/{code}/devices）
 * - カメラ候補にする / カメラとして開始 / 待機に戻す / 切断
 * - ローカルカメラソース選択（USB/内蔵）
 * - WebRTC 受信（iOS → PC）
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Monitor, Smartphone, Tablet, Camera, Usb, X, RefreshCw, Video, VideoOff } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { apiGet, apiPost } from '@/api/client'
import type { SessionParticipant, LocalCameraSource, DeviceType } from '@/types'

interface Props {
  sessionCode: string
  onClose: () => void
}

// ─── デバイスタイプアイコン ───────────────────────────────────────────────────

function DeviceIcon({ type }: { type: DeviceType | null }) {
  const cls = 'w-4 h-4 flex-shrink-0'
  switch (type) {
    case 'iphone': return <Smartphone className={cls} />
    case 'ipad': return <Tablet className={cls} />
    case 'pc': return <Monitor className={cls} />
    case 'usb_camera': return <Usb className={cls} />
    case 'builtin_camera': return <Camera className={cls} />
    default: return <Monitor className={cls} />
  }
}

// ─── 接続ロールバッジ ─────────────────────────────────────────────────────────

function RoleBadge({ role }: { role: string }) {
  const color: Record<string, string> = {
    active_camera: 'bg-red-500 text-white',
    camera_candidate: 'bg-amber-500 text-white',
    analyst: 'bg-purple-500 text-white',
    coach: 'bg-blue-500 text-white',
    viewer: 'bg-gray-500 text-white',
  }
  const label: Record<string, string> = {
    active_camera: 'アクティブカメラ',
    camera_candidate: 'カメラ候補',
    analyst: 'アナリスト',
    coach: 'コーチ',
    viewer: 'ビューワー',
  }
  const cls = color[role] ?? 'bg-gray-600 text-white'
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${cls}`}>
      {label[role] ?? role}
    </span>
  )
}

// ─── WebRTC 接続管理 ──────────────────────────────────────────────────────────

function useWebRTCReceiver(sessionCode: string) {
  const wsRef = useRef<WebSocket | null>(null)
  const pcRef = useRef<RTCPeerConnection | null>(null)
  const [stream, setStream] = useState<MediaStream | null>(null)
  const [activeParticipantId, setActiveParticipantId] = useState<string | null>(null)

  const connect = useCallback(() => {
    if (wsRef.current) return
    const wsUrl = `ws://${window.location.hostname}:8765/ws/camera/${sessionCode}?role=operator`
    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onmessage = async (event) => {
      try {
        const msg = JSON.parse(event.data)
        if (msg.type === 'webrtc_offer') {
          const pc = new RTCPeerConnection({ iceServers: [{ urls: 'stun:stun.l.google.com:19302' }] })
          pcRef.current = pc
          setActiveParticipantId(String(msg.participant_id))

          pc.ontrack = (e) => {
            if (e.streams[0]) setStream(e.streams[0])
          }
          pc.onicecandidate = (e) => {
            if (e.candidate && ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify({
                type: 'ice_candidate',
                target_participant_id: msg.participant_id,
                candidate: e.candidate.candidate,
                sdp_mid: e.candidate.sdpMid,
                sdp_m_line_index: e.candidate.sdpMLineIndex,
              }))
            }
          }

          await pc.setRemoteDescription({ type: 'offer', sdp: msg.sdp })
          const answer = await pc.createAnswer()
          await pc.setLocalDescription(answer)
          ws.send(JSON.stringify({
            type: 'webrtc_answer',
            target_participant_id: msg.participant_id,
            sdp: answer.sdp,
          }))
        } else if (msg.type === 'ice_candidate' && pcRef.current) {
          await pcRef.current.addIceCandidate({
            candidate: msg.candidate,
            sdpMid: msg.sdp_mid,
            sdpMLineIndex: msg.sdp_m_line_index,
          }).catch(() => {})
        } else if (msg.type === 'camera_stop') {
          setStream(null)
          setActiveParticipantId(null)
          pcRef.current?.close()
          pcRef.current = null
        }
      } catch {
        // メッセージ処理エラーは無視
      }
    }

    ws.onclose = () => {
      wsRef.current = null
    }
  }, [sessionCode])

  const requestCamera = useCallback((participantId: number) => {
    wsRef.current?.send(JSON.stringify({
      type: 'camera_request',
      target_participant_id: participantId,
    }))
  }, [])

  const disconnect = useCallback(() => {
    pcRef.current?.close()
    pcRef.current = null
    wsRef.current?.close()
    wsRef.current = null
    setStream(null)
    setActiveParticipantId(null)
  }, [])

  // アンマウント時クリーンアップ
  useEffect(() => () => { disconnect() }, [disconnect])

  return { stream, activeParticipantId, connect, requestCamera, disconnect }
}

// ─── ローカルカメラ列挙 ───────────────────────────────────────────────────────

async function enumerateLocalCameras(): Promise<LocalCameraSource[]> {
  try {
    const devices = await navigator.mediaDevices.enumerateDevices()
    return devices
      .filter((d) => d.kind === 'videoinput')
      .map((d) => ({
        deviceId: d.deviceId,
        label: d.label || `カメラ ${d.deviceId.slice(0, 6)}`,
        kind: 'videoinput' as const,
        type: d.label.toLowerCase().includes('usb') ? 'usb'
          : d.label.toLowerCase().includes('facetime') || d.label.toLowerCase().includes('built') ? 'builtin'
          : 'unknown',
      }))
  } catch {
    return []
  }
}

// ─── メインコンポーネント ─────────────────────────────────────────────────────

export function DeviceManagerPanel({ sessionCode, onClose }: Props) {
  const { t } = useTranslation()
  const isLight = useIsLightMode()
  const [participants, setParticipants] = useState<SessionParticipant[]>([])
  const [localSources, setLocalSources] = useState<LocalCameraSource[]>([])
  const [localStream, setLocalStream] = useState<MediaStream | null>(null)
  const [localActiveId, setLocalActiveId] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const localVideoRef = useRef<HTMLVideoElement>(null)
  const remoteVideoRef = useRef<HTMLVideoElement>(null)

  const { stream: remoteStream, activeParticipantId, connect, requestCamera } = useWebRTCReceiver(sessionCode)

  // WebRTC オペレーター WS に接続
  useEffect(() => {
    connect()
  }, [connect])

  // リモートストリームを video 要素に接続
  useEffect(() => {
    if (remoteVideoRef.current && remoteStream) {
      remoteVideoRef.current.srcObject = remoteStream
    }
  }, [remoteStream])

  // ローカルストリームを video 要素に接続
  useEffect(() => {
    if (localVideoRef.current && localStream) {
      localVideoRef.current.srcObject = localStream
    }
  }, [localStream])

  const fetchDevices = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiGet<{ success: boolean; data: SessionParticipant[] }>(`/sessions/${sessionCode}/devices`)
      if (res.success) setParticipants(res.data)
    } catch {
      // エラーは無視（ポーリングなのでサイレント）
    } finally {
      setLoading(false)
    }
  }, [sessionCode])

  // 初回ロード + 10 秒ポーリング
  useEffect(() => {
    fetchDevices()
    const id = setInterval(fetchDevices, 10_000)
    return () => clearInterval(id)
  }, [fetchDevices])

  // ローカルカメラ列挙
  useEffect(() => {
    enumerateLocalCameras().then(setLocalSources)
  }, [])

  const handleActivateCamera = async (p: SessionParticipant) => {
    try {
      await apiPost(`/sessions/${sessionCode}/devices/${p.id}/activate-camera`, {})
      requestCamera(p.id)
      fetchDevices()
    } catch { /* ignore */ }
  }

  const handleDeactivate = async (p: SessionParticipant) => {
    try {
      await apiPost(`/sessions/${sessionCode}/devices/${p.id}/deactivate-camera`, {})
      fetchDevices()
    } catch { /* ignore */ }
  }

  const handleMakeCandidate = async (p: SessionParticipant) => {
    try {
      await apiPost(`/sessions/${sessionCode}/devices/${p.id}/set-role`, {
        connection_role: 'camera_candidate',
      })
      fetchDevices()
    } catch { /* ignore */ }
  }

  const handleSelectLocalSource = async (source: LocalCameraSource) => {
    // 既存ストリームを停止
    localStream?.getTracks().forEach((t) => t.stop())
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { deviceId: { exact: source.deviceId } },
        audio: false,
      })
      setLocalStream(stream)
      setLocalActiveId(source.deviceId)
    } catch { /* permission denied など */ }
  }

  const handleStopLocal = () => {
    localStream?.getTracks().forEach((t) => t.stop())
    setLocalStream(null)
    setLocalActiveId(null)
  }

  // スタイル
  const panelBg = isLight ? 'bg-white border border-gray-200 shadow-xl' : 'bg-gray-800 border border-gray-700 shadow-2xl'
  const titleColor = isLight ? 'text-gray-900' : 'text-white'
  const subColor = isLight ? 'text-gray-500' : 'text-gray-400'
  const rowBg = isLight ? 'bg-gray-50 hover:bg-gray-100' : 'bg-gray-700/50 hover:bg-gray-700'
  const divider = isLight ? 'border-gray-200' : 'border-gray-700'
  const sectionLabel = isLight ? 'text-gray-600 font-medium text-xs' : 'text-gray-400 font-medium text-xs'

  return (
    <div className={`rounded-xl w-96 p-5 max-h-[85vh] overflow-y-auto ${panelBg}`}>
      {/* ヘッダー */}
      <div className="flex items-center justify-between mb-4">
        <p className={`text-sm font-semibold ${titleColor}`}>
          {t('lan_session.device_manager_title')}
        </p>
        <div className="flex items-center gap-2">
          <button
            onClick={fetchDevices}
            disabled={loading}
            className={`${subColor} hover:${titleColor}`}
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          </button>
          <button onClick={onClose} className={`${subColor} hover:${titleColor}`}>
            <X size={16} />
          </button>
        </div>
      </div>

      {/* ─── リモートカメラ映像プレビュー ────── */}
      {remoteStream && (
        <div className="mb-4">
          <p className={`${sectionLabel} mb-1`}>
            <span className="inline-block w-2 h-2 rounded-full bg-red-500 mr-1 animate-pulse" />
            iOS カメラ受信中（参加者 #{activeParticipantId}）
          </p>
          <video
            ref={remoteVideoRef}
            autoPlay
            playsInline
            muted
            className="w-full rounded-lg aspect-video bg-black object-contain"
          />
        </div>
      )}

      {/* ─── ローカルカメラプレビュー ─────────── */}
      {localStream && (
        <div className="mb-4">
          <div className="flex items-center justify-between mb-1">
            <p className={`${sectionLabel}`}>
              <span className="inline-block w-2 h-2 rounded-full bg-green-500 mr-1 animate-pulse" />
              ローカルカメラ使用中
            </p>
            <button
              onClick={handleStopLocal}
              className="text-xs text-red-400 hover:text-red-300 flex items-center gap-1"
            >
              <VideoOff size={12} />
              {t('lan_session.local_source_stop')}
            </button>
          </div>
          <video
            ref={localVideoRef}
            autoPlay
            playsInline
            muted
            className="w-full rounded-lg aspect-video bg-black object-contain"
          />
        </div>
      )}

      {/* ─── 接続デバイス一覧 ─────────────────── */}
      <p className={`${sectionLabel} mb-2`}>接続デバイス</p>
      {participants.length === 0 ? (
        <p className={`text-xs text-center py-4 ${subColor}`}>{t('lan_session.no_devices')}</p>
      ) : (
        <div className="space-y-2 mb-4">
          {participants.map((p) => (
            <div key={p.id} className={`rounded-lg p-3 ${rowBg}`}>
              <div className="flex items-start gap-2">
                <div className={`mt-0.5 ${subColor}`}>
                  <DeviceIcon type={p.device_type} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className={`text-xs font-medium ${titleColor} truncate`}>
                      {p.device_name ?? `デバイス #${p.id}`}
                    </span>
                    <RoleBadge role={p.connection_role} />
                    {p.connection_state === 'sending_video' && (
                      <span className="text-[10px] text-red-400 font-medium flex items-center gap-0.5">
                        <Video size={10} />送信中
                      </span>
                    )}
                  </div>
                  <p className={`text-[10px] mt-0.5 ${subColor}`}>
                    {p.device_type ? t(`lan_session.device_type_${p.device_type === 'builtin_camera' ? 'builtin' : p.device_type}`) : ''}
                    {p.last_seen_at && (
                      <> · 最終確認: {new Date(p.last_seen_at).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' })}</>
                    )}
                  </p>
                </div>
              </div>

              {/* アクションボタン */}
              <div className="flex gap-1.5 mt-2 flex-wrap">
                {p.connection_role === 'viewer' && p.source_capability === 'camera' && (
                  <button
                    onClick={() => handleMakeCandidate(p)}
                    className="text-[10px] px-2 py-1 rounded bg-amber-600 hover:bg-amber-500 text-white"
                  >
                    {t('lan_session.action_make_candidate')}
                  </button>
                )}
                {p.connection_role === 'camera_candidate' && (
                  <button
                    onClick={() => handleActivateCamera(p)}
                    className="text-[10px] px-2 py-1 rounded bg-red-600 hover:bg-red-500 text-white"
                  >
                    {t('lan_session.action_activate_camera')}
                  </button>
                )}
                {p.connection_role === 'active_camera' && (
                  <button
                    onClick={() => handleDeactivate(p)}
                    className="text-[10px] px-2 py-1 rounded bg-gray-600 hover:bg-gray-500 text-white"
                  >
                    {t('lan_session.action_deactivate')}
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ─── ローカルカメラソース ─────────────── */}
      {localSources.length > 0 && (
        <>
          <div className={`border-t pt-3 ${divider}`}>
            <p className={`${sectionLabel} mb-2`}>{t('lan_session.local_sources_label')}</p>
            <div className="space-y-1.5">
              {localSources.map((src) => (
                <div key={src.deviceId} className={`flex items-center gap-2 rounded-lg px-3 py-2 ${rowBg}`}>
                  <Camera size={12} className={subColor} />
                  <span className={`flex-1 text-xs truncate ${titleColor}`}>{src.label}</span>
                  <span className={`text-[10px] ${subColor}`}>
                    {src.type === 'usb' ? t('lan_session.source_type_usb') : src.type === 'builtin' ? t('lan_session.source_type_builtin') : ''}
                  </span>
                  {localActiveId === src.deviceId ? (
                    <button
                      onClick={handleStopLocal}
                      className="text-[10px] px-2 py-0.5 rounded bg-gray-600 hover:bg-gray-500 text-white"
                    >
                      {t('lan_session.local_source_stop')}
                    </button>
                  ) : (
                    <button
                      onClick={() => handleSelectLocalSource(src)}
                      className="text-[10px] px-2 py-0.5 rounded bg-blue-600 hover:bg-blue-500 text-white"
                    >
                      {t('lan_session.local_source_select')}
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
