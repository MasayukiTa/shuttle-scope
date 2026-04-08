/**
 * デバイス管理パネル — PC オペレーター向けカメラ/デバイス制御 UI（強化版）
 *
 * 機能:
 * - 接続デバイス一覧 + 承認/拒否フロー（approval_status）
 * - カメラ制御（候補 / アクティブ / 待機）
 * - ビューワー映像受信許可（viewer_permission）
 * - ハートビート健全性バッジ（last_heartbeat）
 * - ローカルカメラソース選択・preview
 * - WebRTC 受信（iOS → PC）
 * - WebRTC 送信（PC → ビューワー）
 * - LiveSourceSelector 統合
 * - LiveInferenceOverlay 統合
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Monitor, Smartphone, Tablet, Camera, Usb,
  X, RefreshCw, Video, VideoOff, Shield, ShieldOff,
  CheckCircle2, XCircle, AlertTriangle, Trash2,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { apiGet, apiPost, apiDelete } from '@/api/client'
import { LiveSourceSelector } from './LiveSourceSelector'
import { LiveInferenceOverlay } from './LiveInferenceOverlay'
import type { SessionParticipant, LocalCameraSource, DeviceType } from '@/types'

interface Props {
  sessionCode: string
  onClose: () => void
  onRemoteStream?: (stream: MediaStream | null) => void
  onLocalStream?: (stream: MediaStream | null) => void
}

// ─── ヘルパーコンポーネント ───────────────────────────────────────────────────

function DeviceIcon({ type }: { type: DeviceType | null }) {
  const cls = 'w-4 h-4 flex-shrink-0'
  switch (type) {
    case 'iphone': return <Smartphone className={cls} />
    case 'ipad':   return <Tablet className={cls} />
    case 'pc':     return <Monitor className={cls} />
    case 'usb_camera': return <Usb className={cls} />
    case 'builtin_camera': return <Camera className={cls} />
    default: return <Monitor className={cls} />
  }
}

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
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${color[role] ?? 'bg-gray-600 text-white'}`}>
      {label[role] ?? role}
    </span>
  )
}

function ApprovalBadge({ status }: { status: string }) {
  if (status === 'approved') return (
    <span className="flex items-center gap-0.5 text-[10px] text-green-400">
      <CheckCircle2 size={10} /> 承認済み
    </span>
  )
  if (status === 'rejected') return (
    <span className="flex items-center gap-0.5 text-[10px] text-red-400">
      <XCircle size={10} /> 拒否
    </span>
  )
  return (
    <span className="flex items-center gap-0.5 text-[10px] text-amber-400 animate-pulse">
      <AlertTriangle size={10} /> 承認待ち
    </span>
  )
}

function HeartbeatBadge({ lastHeartbeat }: { lastHeartbeat: string | null }) {
  if (!lastHeartbeat) return null
  const diffSec = (Date.now() - new Date(lastHeartbeat).getTime()) / 1000
  const stale = diffSec > 60
  return (
    <span className={`text-[9px] ${stale ? 'text-red-400' : 'text-gray-500'}`}>
      {stale ? '⚠ 応答なし' : `${Math.round(diffSec)}s前`}
    </span>
  )
}

// ─── WebRTC 受信（iOS → PC）────────────────────────────────────────────────

function useWebRTCReceiver(sessionCode: string) {
  const wsRef = useRef<WebSocket | null>(null)
  const pcRef = useRef<RTCPeerConnection | null>(null)
  const [stream, setStream] = useState<MediaStream | null>(null)
  // stale closure 対策: stream の最新値を ref で保持
  const streamRef = useRef<MediaStream | null>(null)
  const [activeParticipantId, setActiveParticipantId] = useState<string | null>(null)
  // viewer id → pc map (PC → viewers relay)
  const viewerPCsRef = useRef<Map<string, RTCPeerConnection>>(new Map())

  useEffect(() => { streamRef.current = stream }, [stream])

  const sendMessage = useCallback((msg: object) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg))
    }
  }, [])

  const connect = useCallback(() => {
    if (wsRef.current) return
    // Electron(file:) → ws://localhost:8765
    // LAN直接(http:)  → ws://192.168.x.x:8765
    // Cloudflareトンネル(https:) → wss://xxxx.trycloudflare.com (ポートなし)
    const isElectron = window.location.protocol === 'file:'
    const isHttps = window.location.protocol === 'https:'
    const wsProto = isHttps ? 'wss' : 'ws'
    const wsHost = isElectron ? 'localhost:8765' : isHttps ? window.location.host : `${window.location.hostname || 'localhost'}:8765`
    const wsUrl = `${wsProto}://${wsHost}/ws/camera/${sessionCode}?role=operator`
    let ws: WebSocket
    try {
      ws = new WebSocket(wsUrl)
    } catch { return }
    wsRef.current = ws

    ws.onmessage = async (event) => {
      try {
        const msg = JSON.parse(event.data)

        // ─ iOS → PC WebRTC ─
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

        // ─ viewer joined → PC sends offer to viewer ─
        // streamRef.current を使うことで stale closure を回避
        } else if (msg.type === 'viewer_joined' && pcRef.current && streamRef.current) {
          const viewerId = String(msg.viewer_id)
          const currentStream = streamRef.current
          const vpc = new RTCPeerConnection({ iceServers: [{ urls: 'stun:stun.l.google.com:19302' }] })
          viewerPCsRef.current.set(viewerId, vpc)
          currentStream.getTracks().forEach((t) => vpc.addTrack(t, currentStream))
          vpc.onicecandidate = (e) => {
            if (e.candidate && ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify({
                type: 'viewer_ice_candidate',
                viewer_id: viewerId,
                candidate: e.candidate.candidate,
                sdp_mid: e.candidate.sdpMid,
                sdp_m_line_index: e.candidate.sdpMLineIndex,
              }))
            }
          }
          const offer = await vpc.createOffer()
          await vpc.setLocalDescription(offer)
          ws.send(JSON.stringify({
            type: 'viewer_webrtc_offer',
            viewer_id: viewerId,
            sdp: offer.sdp,
          }))

        // ─ viewer answer / ICE ─
        } else if (msg.type === 'viewer_webrtc_answer') {
          const viewerId = String(msg.viewer_id)
          const vpc = viewerPCsRef.current.get(viewerId)
          if (vpc) {
            await vpc.setRemoteDescription({ type: 'answer', sdp: msg.sdp })
          }
        } else if (msg.type === 'viewer_ice_candidate') {
          const viewerId = String(msg.viewer_id)
          const vpc = viewerPCsRef.current.get(viewerId)
          if (vpc) {
            await vpc.addIceCandidate({
              candidate: msg.candidate,
              sdpMid: msg.sdp_mid,
              sdpMLineIndex: msg.sdp_m_line_index,
            }).catch(() => {})
          }

        // ─ viewer left ─
        } else if (msg.type === 'viewer_left') {
          const viewerId = String(msg.viewer_id)
          viewerPCsRef.current.get(viewerId)?.close()
          viewerPCsRef.current.delete(viewerId)

        } else if (msg.type === 'camera_stop') {
          setStream(null)
          setActiveParticipantId(null)
          pcRef.current?.close()
          pcRef.current = null
        }
      } catch { /* ignore */ }
    }
    ws.onclose = () => { wsRef.current = null }
  }, [sessionCode])  // stream を deps から除去: streamRef で最新値を参照

  const requestCamera = useCallback((participantId: number) => {
    wsRef.current?.send(JSON.stringify({ type: 'camera_request', target_participant_id: participantId }))
  }, [])

  const disconnect = useCallback(() => {
    pcRef.current?.close(); pcRef.current = null
    viewerPCsRef.current.forEach((vpc) => vpc.close())
    viewerPCsRef.current.clear()
    wsRef.current?.close(); wsRef.current = null
    setStream(null); setActiveParticipantId(null)
  }, [])

  useEffect(() => () => { disconnect() }, [disconnect])
  return { stream, activeParticipantId, connect, requestCamera, disconnect, sendMessage }
}

// ─── ローカルカメラ列挙 ───────────────────────────────────────────────────────

async function enumerateLocalCameras(): Promise<LocalCameraSource[]> {
  try {
    const devices = await navigator.mediaDevices.enumerateDevices()
    return devices.filter((d) => d.kind === 'videoinput').map((d) => ({
      deviceId: d.deviceId,
      label: d.label || `カメラ ${d.deviceId.slice(0, 6)}`,
      kind: 'videoinput' as const,
      type: d.label.toLowerCase().includes('usb') ? 'usb'
        : d.label.toLowerCase().includes('facetime') || d.label.toLowerCase().includes('built') ? 'builtin'
        : 'unknown',
    }))
  } catch { return [] }
}

// ─── メインコンポーネント ─────────────────────────────────────────────────────

export function DeviceManagerPanel({ sessionCode, onClose, onRemoteStream, onLocalStream }: Props) {
  const { t } = useTranslation()
  const isLight = useIsLightMode()
  const [participants, setParticipants] = useState<SessionParticipant[]>([])
  const [localSources, setLocalSources] = useState<LocalCameraSource[]>([])
  const [localStream, setLocalStream] = useState<MediaStream | null>(null)
  const [localActiveId, setLocalActiveId] = useState<string | null>(null)
  const [localCameraError, setLocalCameraError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [activeTab, setActiveTab] = useState<'devices' | 'sources'>('devices')
  const localVideoRef = useRef<HTMLVideoElement>(null)
  const remoteVideoRef = useRef<HTMLVideoElement>(null)

  const { stream: remoteStream, activeParticipantId, connect, requestCamera, sendMessage } = useWebRTCReceiver(sessionCode)

  useEffect(() => { connect() }, [connect])
  useEffect(() => {
    if (remoteVideoRef.current && remoteStream) remoteVideoRef.current.srcObject = remoteStream
    onRemoteStream?.(remoteStream)
  }, [remoteStream, onRemoteStream])
  useEffect(() => {
    if (localVideoRef.current && localStream) localVideoRef.current.srcObject = localStream
    onLocalStream?.(localStream)
  }, [localStream, onLocalStream])

  const fetchDevices = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiGet<{ success: boolean; data: SessionParticipant[] }>(`/sessions/${sessionCode}/devices`)
      if (res.success) setParticipants(res.data)
    } catch { } finally { setLoading(false) }
  }, [sessionCode])

  useEffect(() => {
    fetchDevices()
    const id = setInterval(fetchDevices, 10_000)
    return () => clearInterval(id)
  }, [fetchDevices])

  useEffect(() => { enumerateLocalCameras().then(setLocalSources) }, [])

  // ─── アクションハンドラー ───────────────────────────────────────────────

  const post = async (path: string, body: object = {}) => {
    await apiPost(`/sessions/${sessionCode}${path}`, body)
    fetchDevices()
  }

  const handlePurgeDisconnected = async () => {
    try {
      await apiDelete(`/sessions/${sessionCode}/devices`)
    } catch { /* 失敗は無視 */ }
    fetchDevices()
  }

  const handleDeleteDevice = async (p: SessionParticipant) => {
    try {
      await apiDelete(`/sessions/${sessionCode}/devices/${p.id}`)
    } catch { /* 失敗は無視 */ }
    fetchDevices()
  }

  const handleApprove = (p: SessionParticipant) => post(`/devices/${p.id}/approve`)
  const handleReject  = (p: SessionParticipant) => post(`/devices/${p.id}/reject`)
  const handleActivateCamera = async (p: SessionParticipant) => {
    await post(`/devices/${p.id}/activate-camera`)
    requestCamera(p.id)
  }
  const handleDeactivate = async (p: SessionParticipant) => {
    await post(`/devices/${p.id}/deactivate-camera`)
    sendMessage({ type: 'camera_deactivate', target_participant_id: p.id })
  }
  const handleMakeCandidate  = (p: SessionParticipant) => post(`/devices/${p.id}/set-role`, { connection_role: 'camera_candidate' })
  const handleAllowVideo     = (p: SessionParticipant) => post(`/devices/${p.id}/set-viewer-permission`, { viewer_permission: 'allowed' })
  const handleBlockVideo     = (p: SessionParticipant) => post(`/devices/${p.id}/set-viewer-permission`, { viewer_permission: 'blocked' })

  const handleSelectLocalSource = async (src: LocalCameraSource) => {
    localStream?.getTracks().forEach((t) => t.stop())
    setLocalCameraError(null)
    try {
      // deviceId が空の場合（権限未取得）は制約なしで要求し、権限取得後に再列挙
      const videoConstraint: MediaTrackConstraints | boolean = src.deviceId
        ? { deviceId: { exact: src.deviceId } }
        : true
      const s = await navigator.mediaDevices.getUserMedia({ video: videoConstraint, audio: false })
      setLocalStream(s)
      setLocalActiveId(src.deviceId)
      // 権限取得後にデバイス一覧を再取得してラベル・ID を正確にする
      enumerateLocalCameras().then(setLocalSources)
    } catch {
      setLocalCameraError('カメラを起動できませんでした。OS設定でカメラへのアクセスを許可してください。')
    }
  }
  const handleStopLocal = () => {
    localStream?.getTracks().forEach((t) => t.stop())
    setLocalStream(null)
    setLocalActiveId(null)
    setLocalCameraError(null)
    // onLocalStreamはuseEffectで自動発火（localStream→null）
  }

  // ─── スタイル ────────────────────────────────────────────────────────

  const panelBg = isLight ? 'bg-white border border-gray-200 shadow-xl' : 'bg-gray-800 border border-gray-700 shadow-2xl'
  const titleColor = isLight ? 'text-gray-900' : 'text-white'
  const subColor = isLight ? 'text-gray-500' : 'text-gray-400'
  const rowBg = isLight ? 'bg-gray-50 hover:bg-gray-100' : 'bg-gray-700/50 hover:bg-gray-700'
  const divider = isLight ? 'border-gray-200' : 'border-gray-700'
  const tabActive = isLight ? 'border-blue-500 text-blue-600' : 'border-blue-400 text-blue-300'
  const tabInactive = isLight ? 'border-transparent text-gray-500 hover:text-gray-700' : 'border-transparent text-gray-500 hover:text-gray-300'

  return (
    <div className={`rounded-xl w-[420px] p-5 max-h-[88vh] overflow-y-auto ${panelBg}`}>
      {/* ヘッダー */}
      <div className="flex items-center justify-between mb-3">
        <p className={`text-sm font-semibold ${titleColor}`}>{t('lan_session.device_manager_title')}</p>
        <div className="flex items-center gap-2">
          <button
            onClick={handlePurgeDisconnected}
            title="切断済みデバイスを一括削除"
            className={`${subColor} hover:text-red-400`}
          >
            <Trash2 size={14} />
          </button>
          <button onClick={fetchDevices} className={`${subColor}`}>
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          </button>
          <button onClick={onClose} className={`${subColor}`}><X size={16} /></button>
        </div>
      </div>

      {/* タブ */}
      <div className={`flex border-b mb-4 ${divider}`}>
        {(['devices', 'sources'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-3 py-1.5 text-xs font-medium border-b-2 transition-colors ${
              activeTab === tab ? tabActive : tabInactive
            }`}
          >
            {tab === 'devices' ? '接続デバイス' : 'ソース管理'}
          </button>
        ))}
      </div>

      {/* ─── リモートカメラ映像 ── */}
      {remoteStream && (
        <div className="mb-4 relative">
          <p className={`text-[10px] mb-1 ${subColor}`}>
            <span className="inline-block w-2 h-2 rounded-full bg-red-500 mr-1 animate-pulse" />
            iOS カメラ受信中（参加者 #{activeParticipantId}）
          </p>
          <div className="relative">
            <video
              ref={remoteVideoRef}
              autoPlay playsInline muted
              className="w-full rounded-lg aspect-video bg-black object-contain"
            />
            <LiveInferenceOverlay
              videoRef={remoteVideoRef}
              sessionCode={sessionCode}
              className="absolute inset-0"
            />
          </div>
        </div>
      )}

      {/* ─── ローカルカメラ映像 ── */}
      {localStream && (
        <div className="mb-4">
          <div className="flex items-center justify-between mb-1">
            <p className={`text-[10px] ${subColor}`}>
              <span className="inline-block w-2 h-2 rounded-full bg-green-500 mr-1 animate-pulse" />
              ローカルカメラ使用中
            </p>
            <button onClick={handleStopLocal} className="text-xs text-red-400 hover:text-red-300 flex items-center gap-1">
              <VideoOff size={12} />{t('lan_session.local_source_stop')}
            </button>
          </div>
          <video
            ref={localVideoRef}
            autoPlay playsInline muted
            className="w-full rounded-lg aspect-video bg-black object-contain"
          />
        </div>
      )}

      {/* ─── タブコンテンツ ── */}

      {activeTab === 'devices' && (
        <>
          {/* 承認待ちデバイス（優先表示） */}
          {participants.filter((p) => p.approval_status === 'pending').length > 0 && (
            <div className="mb-3 p-3 rounded-lg border border-amber-500/40 bg-amber-500/10">
              <p className="text-xs text-amber-400 font-medium mb-2">
                <AlertTriangle size={12} className="inline mr-1" />
                承認待ちのデバイス
              </p>
              {participants.filter((p) => p.approval_status === 'pending').map((p) => (
                <div key={p.id} className="flex items-center justify-between py-1">
                  <div className="flex items-center gap-2">
                    <DeviceIcon type={p.device_type} />
                    <span className="text-xs text-white">{p.device_name ?? `デバイス #${p.id}`}</span>
                  </div>
                  <div className="flex gap-1.5">
                    <button onClick={() => handleApprove(p)} className="text-[10px] px-2 py-0.5 rounded bg-green-600 hover:bg-green-500 text-white flex items-center gap-0.5">
                      <CheckCircle2 size={10} />{t('device_approval.approve')}
                    </button>
                    <button onClick={() => handleReject(p)} className="text-[10px] px-2 py-0.5 rounded bg-red-700 hover:bg-red-600 text-white flex items-center gap-0.5">
                      <XCircle size={10} />{t('device_approval.reject')}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* 全デバイス一覧 */}
          {participants.length === 0 ? (
            <p className={`text-xs text-center py-4 ${subColor}`}>{t('lan_session.no_devices')}</p>
          ) : (
            <div className="space-y-2">
              {participants.map((p) => (
                <div key={p.id} className={`rounded-lg p-3 ${rowBg}`}>
                  <div className="flex items-start gap-2">
                    <div className={`mt-0.5 ${subColor}`}><DeviceIcon type={p.device_type} /></div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <span className={`text-xs font-medium truncate ${titleColor}`}>
                          {p.device_name ?? `デバイス #${p.id}`}
                        </span>
                        <RoleBadge role={p.connection_role} />
                        <ApprovalBadge status={p.approval_status} />
                      </div>
                    </div>
                    <button
                      onClick={() => handleDeleteDevice(p)}
                      title="このデバイスを削除"
                      className="shrink-0 text-gray-600 hover:text-red-400 transition-colors"
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                  <div className="ml-6 mt-0.5">
                    <div className={`flex items-center gap-2 text-[10px] ${subColor}`}>
                      {p.connection_state === 'sending_video' && (
                        <span className="text-red-400 flex items-center gap-0.5">
                          <Video size={10} />送信中
                        </span>
                      )}
                      {p.device_class && <span>{p.device_class}</span>}
                      <HeartbeatBadge lastHeartbeat={p.last_heartbeat} />
                      {p.viewer_permission !== 'default' && (
                        <span className={p.viewer_permission === 'allowed' ? 'text-green-400' : 'text-red-400'}>
                          {p.viewer_permission === 'allowed' ? '映像受信許可' : '映像受信停止'}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* アクションボタン */}
                  {p.approval_status === 'approved' && (
                    <div className="flex gap-1.5 mt-2 flex-wrap">
                      {p.connection_role === 'viewer' && p.source_capability === 'camera' && (
                        <button onClick={() => handleMakeCandidate(p)}
                          className="text-[10px] px-2 py-1 rounded bg-amber-600 hover:bg-amber-500 text-white">
                          {t('lan_session.action_make_candidate')}
                        </button>
                      )}
                      {p.connection_role === 'camera_candidate' && (
                        <button onClick={() => handleActivateCamera(p)}
                          className="text-[10px] px-2 py-1 rounded bg-red-600 hover:bg-red-500 text-white">
                          {t('lan_session.action_activate_camera')}
                        </button>
                      )}
                      {p.connection_role === 'active_camera' && (
                        <>
                          <button onClick={() => requestCamera(p.id)}
                            className="text-[10px] px-2 py-1 rounded bg-red-700 hover:bg-red-600 text-white flex items-center gap-0.5">
                            <Video size={9} />カメラ再リクエスト
                          </button>
                          <button onClick={() => handleDeactivate(p)}
                            className="text-[10px] px-2 py-1 rounded bg-gray-600 hover:bg-gray-500 text-white">
                            {t('lan_session.action_deactivate')}
                          </button>
                        </>
                      )}
                      {/* ビューワー映像許可 */}
                      {p.device_class !== 'phone' && (
                        p.viewer_permission !== 'allowed' ? (
                          <button onClick={() => handleAllowVideo(p)}
                            className="text-[10px] px-2 py-1 rounded bg-blue-700 hover:bg-blue-600 text-white flex items-center gap-0.5">
                            <Shield size={9} />{t('lan_session.action_allow_receive')}
                          </button>
                        ) : (
                          <button onClick={() => handleBlockVideo(p)}
                            className="text-[10px] px-2 py-1 rounded bg-gray-700 hover:bg-gray-600 text-white flex items-center gap-0.5">
                            <ShieldOff size={9} />{t('lan_session.action_stop_receive')}
                          </button>
                        )
                      )}
                      {p.device_class === 'phone' && (
                        <span className="text-[9px] text-gray-500">{t('viewer_relay.phone_blocked')}</span>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* ローカルカメラソース */}
          {localSources.length > 0 && (
            <div className={`border-t pt-3 mt-3 ${divider}`}>
              <p className={`text-xs font-medium mb-2 ${titleColor}`}>{t('lan_session.local_sources_label')}</p>
              {localCameraError && (
                <p className="text-[10px] text-red-400 mb-2 flex items-center gap-1">
                  <XCircle size={10} />{localCameraError}
                </p>
              )}
              <div className="space-y-1.5">
                {localSources.map((src) => (
                  <div key={src.deviceId} className={`flex items-center gap-2 rounded-lg px-3 py-2 ${rowBg}`}>
                    <Camera size={12} className={subColor} />
                    <span className={`flex-1 text-xs truncate ${titleColor}`}>{src.label}</span>
                    <span className={`text-[10px] ${subColor}`}>
                      {src.type === 'usb' ? t('lan_session.source_type_usb') : src.type === 'builtin' ? t('lan_session.source_type_builtin') : ''}
                    </span>
                    {localActiveId === src.deviceId ? (
                      <button onClick={handleStopLocal}
                        className="text-[10px] px-2 py-0.5 rounded bg-gray-600 hover:bg-gray-500 text-white">
                        {t('lan_session.local_source_stop')}
                      </button>
                    ) : (
                      <button onClick={() => handleSelectLocalSource(src)}
                        className="text-[10px] px-2 py-0.5 rounded bg-blue-600 hover:bg-blue-500 text-white">
                        {t('lan_session.local_source_select')}
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {activeTab === 'sources' && (
        <LiveSourceSelector sessionCode={sessionCode} />
      )}
    </div>
  )
}
