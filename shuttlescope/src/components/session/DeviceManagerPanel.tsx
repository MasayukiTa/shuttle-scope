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
import { useTranslation } from 'react-i18next'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { apiGet, apiPost, apiDelete } from '@/api/client'
import { LiveSourceSelector } from './LiveSourceSelector'
import { LiveInferenceOverlay } from './LiveInferenceOverlay'
import { RealtimeYoloOverlay } from './RealtimeYoloOverlay'
import { useRealtimeYolo } from '@/hooks/useRealtimeYolo'
import type { SessionParticipant, LocalCameraSource, DeviceType } from '@/types'
import { MIcon } from '@/components/common/MIcon'
import { cameraWsUrl } from '@/utils/cameraWs'

interface RemoteHealth {
  wsConnected: boolean
  connectionState: RTCPeerConnectionState | null
  turnInUse: boolean | null
}

interface Props {
  sessionCode: string
  onClose: () => void
  onRemoteStream?: (stream: MediaStream | null) => void
  onLocalStream?: (stream: MediaStream | null) => void
  onHealthChange?: (health: RemoteHealth) => void
}

// ─── ヘルパーコンポーネント ───────────────────────────────────────────────────

function DeviceIcon({ type }: { type: DeviceType | null }) {
  const cls = 'w-4 h-4 flex-shrink-0'
  switch (type) {
    case 'iphone': return <MIcon name="smartphone" className={cls} />
    case 'ipad':   return <MIcon name="tablet" className={cls} />
    case 'pc':     return <MIcon name="monitor" className={cls} />
    case 'usb_camera': return <MIcon name="usb" className={cls} />
    case 'builtin_camera': return <MIcon name="photo_camera" className={cls} />
    default: return <MIcon name="monitor" className={cls} />
  }
}

function _RoleBadge({ role }: { role: string }) {
  const color: Record<string, string> = {
    active_camera: 'bg-[var(--ss-bad)] text-white',
    camera_candidate: 'bg-[var(--ss-warn)] text-white',
    analyst: 'bg-[var(--ss-brand)] text-white',
    coach: 'bg-[var(--ss-brand)] text-white',
    viewer: 'bg-[var(--ss-t2)] text-white',
  }
  const label: Record<string, string> = {
    active_camera: 'アクティブカメラ',
    camera_candidate: 'カメラ候補',
    analyst: 'アナリスト',
    coach: 'コーチ',
    viewer: 'ビューワー',
  }
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded-ss-pill font-medium ${color[role] ?? 'bg-[var(--ss-t2)] text-white'}`}>
      {label[role] ?? role}
    </span>
  )
}

function ApprovalBadge({ status }: { status: string }) {
  const { t } = useTranslation()
  if (status === 'approved') return (
    <span className="flex items-center gap-0.5 text-[10px] text-[var(--ss-success)]">
      <MIcon name="check_circle" size={10} /> {t('auto.DeviceManagerPanel.approved')}
    </span>
  )
  if (status === 'rejected') return (
    <span className="flex items-center gap-0.5 text-[10px] text-[var(--ss-bad)]">
      <MIcon name="cancel" size={10} /> {t('auto.DeviceManagerPanel.rejected')}
    </span>
  )
  return (
    <span className="flex items-center gap-0.5 text-[10px] text-[var(--ss-warn)] animate-pulse">
      <MIcon name="warning" size={10} /> {t('auto.DeviceManagerPanel.pending')}
    </span>
  )
}

function HeartbeatBadge({ lastHeartbeat }: { lastHeartbeat: string | null }) {
  if (!lastHeartbeat) return null
  const diffSec = (Date.now() - new Date(lastHeartbeat).getTime()) / 1000
  const stale = diffSec > 60
  return (
    <span className={`text-[9px] inline-flex items-center gap-0.5 ${stale ? 'text-[var(--ss-bad)]' : 'text-[var(--ss-t3)]'}`}>
      {stale ? <><MIcon name="warning" size={9} />応答なし</> : `${Math.round(diffSec)}s前`}
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
  const [connectionState, setConnectionState] = useState<RTCPeerConnectionState | null>(null)
  const [iceGatheringState, setIceGatheringState] = useState<RTCIceGatheringState | null>(null)
  const [wsConnected, setWsConnected] = useState(false)
  const [wsReconnecting, setWsReconnecting] = useState(false)
  const [wsReconnectCount, setWsReconnectCount] = useState(0)
  const [turnInUse, setTurnInUse] = useState<boolean | null>(null)
  const statsTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const reconnectCountRef = useRef(0)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const manualDisconnectRef = useRef(false)
  // ICE サーバー設定（バックエンドから取得、TURN 含む）
  const iceServersRef = useRef<RTCIceServer[]>([{ urls: 'stun:stun.l.google.com:19302' }])
  // viewer id → pc map (PC → viewers relay)
  const viewerPCsRef = useRef<Map<string, RTCPeerConnection>>(new Map())

  useEffect(() => { streamRef.current = stream }, [stream])

  // TURN relay 検出: 選択済み candidate pair が relay 型かチェック
  const startStatsPolling = useCallback((pc: RTCPeerConnection) => {
    statsTimerRef.current = setInterval(async () => {
      try {
        const stats = await pc.getStats()
        let relayInUse = false
        stats.forEach((report) => {
          if (report.type === 'candidate-pair' && report.state === 'succeeded') {
            const localId = report.localCandidateId
            stats.forEach((r) => {
              if (r.id === localId && r.type === 'local-candidate' && r.candidateType === 'relay') {
                relayInUse = true
              }
            })
          }
        })
        setTurnInUse(relayInUse)
      } catch { /* ignore */ }
    }, 5000)
  }, [])

  const stopStatsPolling = useCallback(() => {
    if (statsTimerRef.current) {
      clearInterval(statsTimerRef.current)
      statsTimerRef.current = null
    }
    setTurnInUse(null)
  }, [])

  const sendMessage = useCallback((msg: object) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg))
    }
  }, [])

  const connect = useCallback(async () => {
    if (wsRef.current) return
    manualDisconnectRef.current = false

    // ICE サーバー設定を取得（TURN が有効な場合はリレー経由）
    try {
      const iceCfg = await apiGet<{ success: boolean; data: { ice_servers: RTCIceServer[] } }>('/webrtc/ice-config')
      if (iceCfg.success && iceCfg.data.ice_servers.length > 0) {
        iceServersRef.current = iceCfg.data.ice_servers
      }
    } catch { /* バックエンド未起動時はデフォルト STUN を使用 */ }

    let ws: WebSocket
    try {
      ws = new WebSocket(cameraWsUrl(sessionCode, { role: 'operator' }))
    } catch { return }
    wsRef.current = ws

    ws.onopen = () => {
      setWsConnected(true)
      setWsReconnecting(false)
      setWsReconnectCount(0)
      reconnectCountRef.current = 0
    }
    ws.onclose = () => {
      wsRef.current = null
      setWsConnected(false)
      if (manualDisconnectRef.current) return
      const next = reconnectCountRef.current + 1
      if (next > 5) { setWsReconnecting(false); return }
      reconnectCountRef.current = next
      setWsReconnectCount(next)
      setWsReconnecting(true)
      reconnectTimerRef.current = setTimeout(() => { connect() }, 5_000)
    }

    ws.onmessage = async (event) => {
      try {
        const msg = JSON.parse(event.data)

        // ─ iOS → PC WebRTC ─
        if (msg.type === 'webrtc_offer') {
          stopStatsPolling()
          // ハンドオフ安全化: 既存 PC を先にクローズ（ダブルアクティブ防止）
          if (pcRef.current) {
            pcRef.current.close()
            pcRef.current = null
            setStream(null)
          }
          const pc = new RTCPeerConnection({ iceServers: iceServersRef.current })
          pcRef.current = pc
          setActiveParticipantId(String(msg.participant_id))
          setConnectionState(pc.connectionState)
          setIceGatheringState(pc.iceGatheringState)
          pc.onicegatheringstatechange = () => setIceGatheringState(pc.iceGatheringState)
          pc.onconnectionstatechange = () => {
            setConnectionState(pc.connectionState)
            if (pc.connectionState === 'connected') startStatsPolling(pc)
          }
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
          const vpc = new RTCPeerConnection({ iceServers: iceServersRef.current })
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
          stopStatsPolling()
          setStream(null)
          setActiveParticipantId(null)
          setConnectionState(null)
          setIceGatheringState(null)
          pcRef.current?.close()
          pcRef.current = null
        }
      } catch { /* ignore */ }
    }
  }, [sessionCode, startStatsPolling, stopStatsPolling])  // stream を deps から除去: streamRef で最新値を参照

  const requestCamera = useCallback((participantId: number) => {
    wsRef.current?.send(JSON.stringify({ type: 'camera_request', target_participant_id: participantId }))
  }, [])

  const disconnect = useCallback(() => {
    manualDisconnectRef.current = true
    if (reconnectTimerRef.current) { clearTimeout(reconnectTimerRef.current); reconnectTimerRef.current = null }
    reconnectCountRef.current = 0
    stopStatsPolling()
    pcRef.current?.close(); pcRef.current = null
    viewerPCsRef.current.forEach((vpc) => vpc.close())
    viewerPCsRef.current.clear()
    wsRef.current?.close(); wsRef.current = null
    setStream(null); setActiveParticipantId(null); setConnectionState(null)
    setIceGatheringState(null); setWsConnected(false); setWsReconnecting(false); setWsReconnectCount(0)
  }, [stopStatsPolling])

  useEffect(() => () => { disconnect() }, [disconnect])
  return { stream, activeParticipantId, connectionState, iceGatheringState, wsConnected, wsReconnecting, wsReconnectCount, turnInUse, connect, requestCamera, disconnect, sendMessage }
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

// ─── デバイス行コンポーネント ─────────────────────────────────────────────────

interface DeviceRowProps {
  p: SessionParticipant
  isLight: boolean
  titleColor: string
  subColor: string
  rowBg: string
  onApprove: (p: SessionParticipant) => void
  onReject: (p: SessionParticipant) => void
  onActivateCamera: (p: SessionParticipant) => void
  onDeactivate: (p: SessionParticipant) => void
  onRequestCamera: (p: SessionParticipant) => void
  onMakeCandidate: (p: SessionParticipant) => void
  onAllowVideo: (p: SessionParticipant) => void
  onBlockVideo: (p: SessionParticipant) => void
  onDeleteDevice: (p: SessionParticipant) => void
  t: (key: string) => string
}

function DeviceRow({ p, _isLight, titleColor, subColor, rowBg, onApprove, onReject, onActivateCamera, onDeactivate, onRequestCamera, onMakeCandidate, onAllowVideo, onBlockVideo, onDeleteDevice, t }: DeviceRowProps) {

  const isStaleCamera = p.connection_role === 'active_camera' && p.last_heartbeat
    ? (Date.now() - new Date(p.last_heartbeat).getTime()) / 1000 > 60
    : false

  return (
    <div className={`rounded-ss-md p-3 ${rowBg} ${isStaleCamera ? 'border border-[var(--ss-warning-border)]' : ''}`}>
      <div className="flex items-start gap-2">
        <div className={`mt-0.5 ${subColor}`}><DeviceIcon type={p.device_type} /></div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className={`text-xs font-medium truncate ${titleColor}`}>
              {p.device_name ?? `デバイス #${p.id}`}
            </span>
            <ApprovalBadge status={p.approval_status} />
            {(p.device_type === 'iphone' || p.device_type === 'ipad') && (
              <span className="text-[9px] px-1 py-0.5 rounded-ss-sm bg-[var(--ss-brand-tint)] text-[var(--ss-brand)]">{t('auto.DeviceManagerPanel.k1')}</span>
            )}
            {p.device_type === 'pc' && (
              <span className="text-[9px] px-1 py-0.5 rounded-ss-sm bg-[var(--ss-surface-3)] text-[var(--ss-t3)]">{t('auto.DeviceManagerPanel.k2')}</span>
            )}
            {isStaleCamera && (
              <span className="text-[9px] px-1 py-0.5 rounded-ss-sm bg-[var(--ss-warn-tint)] text-[var(--ss-warn)] flex items-center gap-0.5">
                <MIcon name="warning" size={8} />{t('handoff.stale_warning')}
              </span>
            )}
          </div>
        </div>
        <button
          onClick={() => onDeleteDevice(p)}
          title={t('auto.DeviceManagerPanel.k11')}
          className="shrink-0 text-[var(--ss-t3)] hover:text-[var(--ss-bad)] transition-colors duration-base ease-out"
        >
          <MIcon name="delete" size={12} />
        </button>
      </div>
      <div className="ml-6 mt-0.5">
        <div className={`flex items-center gap-2 text-[10px] ${subColor}`}>
          <span className={`flex items-center gap-0.5 ${p.is_connected ? 'text-[var(--ss-success)]' : 'text-[var(--ss-t3)]'}`}>
            <span className={`w-1 h-1 rounded-full ${p.is_connected ? 'bg-[var(--ss-success)]' : 'bg-[var(--ss-t3)]'}`} />
            {p.is_connected ? '接続' : '切断'}
          </span>
          {p.connection_state === 'sending_video' && (
            <span className="text-[var(--ss-bad)] flex items-center gap-0.5">
              <MIcon name="videocam" size={10} />{t('auto.DeviceManagerPanel.sending')}
            </span>
          )}
          {p.connection_state === 'receiving_video' && (
            <span className="text-[var(--ss-brand)] flex items-center gap-0.5">
              <MIcon name="videocam" size={10} />{t('auto.DeviceManagerPanel.receiving')}
            </span>
          )}
          {p.device_class && <span>{p.device_class}</span>}
          <HeartbeatBadge lastHeartbeat={p.last_heartbeat} />
          {p.viewer_permission !== 'default' && (
            <span className={p.viewer_permission === 'allowed' ? 'text-[var(--ss-success)]' : 'text-[var(--ss-bad)]'}>
              {p.viewer_permission === 'allowed' ? '映像受信許可' : '映像受信停止'}
            </span>
          )}
        </div>
      </div>

      {/* アクションボタン */}
      {p.approval_status === 'approved' && (
        <div className="flex gap-1.5 mt-2 flex-wrap">
          {p.connection_role === 'viewer' && p.source_capability === 'camera' && (
            <button onClick={() => onMakeCandidate(p)}
              className="text-[10px] px-2 py-1 rounded-ss-sm bg-[var(--ss-warn)] hover:opacity-90 transition-colors duration-base ease-out text-white">
              {t('lan_session.action_make_candidate')}
            </button>
          )}
          {p.connection_role === 'camera_candidate' && (
            <button onClick={() => onActivateCamera(p)}
              className="text-[10px] px-2 py-1 rounded-ss-sm bg-[var(--ss-bad)] hover:opacity-90 transition-colors duration-base ease-out text-white">
              {t('lan_session.action_activate_camera')}
            </button>
          )}
          {p.connection_role === 'active_camera' && (
            <>
              <button onClick={() => onRequestCamera(p)}
                className="text-[10px] px-2 py-1 rounded-ss-sm bg-[var(--ss-bad)] hover:opacity-90 transition-colors duration-base ease-out text-white flex items-center gap-0.5">
                <MIcon name="videocam" size={9} />{isStaleCamera ? t('handoff.stale_rerequest') : 'カメラ再リクエスト'}
              </button>
              <button onClick={() => onDeactivate(p)}
                className="text-[10px] px-2 py-1 rounded-ss-sm bg-[var(--ss-t2)] hover:opacity-90 transition-colors duration-base ease-out text-white">
                {t('lan_session.action_deactivate')}
              </button>
            </>
          )}
          {/* ビューワー映像許可 */}
          {p.device_class !== 'phone' && (
            p.viewer_permission !== 'allowed' ? (
              <button onClick={() => onAllowVideo(p)}
                className="text-[10px] px-2 py-1 rounded-ss-sm bg-[var(--ss-brand)] hover:bg-[var(--ss-brand-hover)] transition-colors duration-base ease-out text-white flex items-center gap-0.5">
                <MIcon name="shield" size={9} />{t('lan_session.action_allow_receive')}
              </button>
            ) : (
              <button onClick={() => onBlockVideo(p)}
                className="text-[10px] px-2 py-1 rounded-ss-sm bg-[var(--ss-surface-3)] hover:bg-[var(--ss-border-strong)] transition-colors duration-base ease-out text-[var(--ss-t1)] flex items-center gap-0.5">
                <MIcon name="gpp_bad" size={9} />{t('lan_session.action_stop_receive')}
              </button>
            )
          )}
          {p.device_class === 'phone' && (
            <span className="text-[9px] text-[var(--ss-t3)]">{t('viewer_relay.phone_blocked')}</span>
          )}
        </div>
      )}
      {p.approval_status === 'pending' && (
        <div className="flex gap-1.5 mt-2">
          <button onClick={() => onApprove(p)} className="text-[10px] px-2 py-0.5 rounded-ss-sm bg-[var(--ss-success)] hover:opacity-90 transition-colors duration-base ease-out text-white flex items-center gap-0.5">
            <MIcon name="check_circle" size={10} />{t('device_approval.approve')}
          </button>
          <button onClick={() => onReject(p)} className="text-[10px] px-2 py-0.5 rounded-ss-sm bg-[var(--ss-bad)] hover:opacity-90 transition-colors duration-base ease-out text-white flex items-center gap-0.5">
            <MIcon name="cancel" size={10} />{t('device_approval.reject')}
          </button>
        </div>
      )}
    </div>
  )
}

// ─── グループ別デバイス一覧 ───────────────────────────────────────────────────

interface DeviceGroupedListProps extends Omit<DeviceRowProps, 'p'> {
  participants: SessionParticipant[]
  divider: string
}

function DeviceGroupedList({ participants, isLight, titleColor, subColor, rowBg, divider, ...rowProps }: DeviceGroupedListProps) {
  const activeCamera = participants.filter((p) => p.connection_role === 'active_camera')
  const candidates = participants.filter((p) => p.connection_role === 'camera_candidate')
  const viewers = participants.filter((p) => p.connection_role === 'viewer')
  const others = participants.filter((p) => !['active_camera', 'camera_candidate', 'viewer'].includes(p.connection_role))

  const GroupHeader = ({ label, iconName, count }: { label: string; iconName: string; count: number }) => (
    <div className="flex items-center gap-1.5 text-[10px] font-medium py-1.5 text-[var(--ss-t3)]">
      <MIcon name={iconName} size={11} />
      <span className="uppercase tracking-wide">{label}</span>
      <span className="ml-auto text-[9px] px-1.5 py-0.5 rounded-ss-pill bg-[var(--ss-surface-3)] text-[var(--ss-t3)]">{count}</span>
    </div>
  )

  return (
    <div className="space-y-1">
      {activeCamera.length > 0 && (
        <div>
          <GroupHeader label="アクティブカメラ" iconName="photo_camera" count={activeCamera.length} />
          <div className="space-y-2">
            {activeCamera.map((p) => <DeviceRow key={p.id} p={p} isLight={isLight} titleColor={titleColor} subColor={subColor} rowBg={rowBg} {...rowProps} />)}
          </div>
        </div>
      )}

      {candidates.length > 0 && (
        <div className={activeCamera.length > 0 ? `pt-2 mt-1 border-t ${divider}` : ''}>
          <GroupHeader label="カメラ候補" iconName="videocam" count={candidates.length} />
          <div className="space-y-2">
            {candidates.map((p) => <DeviceRow key={p.id} p={p} isLight={isLight} titleColor={titleColor} subColor={subColor} rowBg={rowBg} {...rowProps} />)}
          </div>
        </div>
      )}

      {viewers.length > 0 && (
        <div className={activeCamera.length > 0 || candidates.length > 0 ? `pt-2 mt-1 border-t ${divider}` : ''}>
          <GroupHeader label="リモートビューワー" iconName="visibility" count={viewers.length} />
          <div className="space-y-2">
            {viewers.map((p) => <DeviceRow key={p.id} p={p} isLight={isLight} titleColor={titleColor} subColor={subColor} rowBg={rowBg} {...rowProps} />)}
          </div>
        </div>
      )}

      {others.length > 0 && (
        <div className={activeCamera.length > 0 || candidates.length > 0 || viewers.length > 0 ? `pt-2 mt-1 border-t ${divider}` : ''}>
          <GroupHeader label="その他" iconName="group" count={others.length} />
          <div className="space-y-2">
            {others.map((p) => <DeviceRow key={p.id} p={p} isLight={isLight} titleColor={titleColor} subColor={subColor} rowBg={rowBg} {...rowProps} />)}
          </div>
        </div>
      )}
    </div>
  )
}

// ─── メインコンポーネント ─────────────────────────────────────────────────────

export function DeviceManagerPanel({ sessionCode, onClose, onRemoteStream, onLocalStream, onHealthChange }: Props) {
  const { t } = useTranslation()
  const isLight = useIsLightMode()
  const [participants, setParticipants] = useState<SessionParticipant[]>([])
  const [localSources, setLocalSources] = useState<LocalCameraSource[]>([])
  const [localStream, setLocalStream] = useState<MediaStream | null>(null)
  const [localActiveId, setLocalActiveId] = useState<string | null>(null)
  const [localCameraError, setLocalCameraError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [activeTab, setActiveTab] = useState<'devices' | 'sources'>('devices')
  // handoff confirmation: participant waiting to be activated
  const [handoffTarget, setHandoffTarget] = useState<SessionParticipant | null>(null)
  // local-over-remote confirmation
  const [localSwitchPending, setLocalSwitchPending] = useState<LocalCameraSource | null>(null)
  const localVideoRef = useRef<HTMLVideoElement>(null)
  const remoteVideoRef = useRef<HTMLVideoElement>(null)

  const { stream: remoteStream, activeParticipantId, connectionState, iceGatheringState, wsConnected, wsReconnecting, wsReconnectCount, turnInUse, connect, requestCamera, sendMessage } = useWebRTCReceiver(sessionCode)

  // リアルタイム YOLO トグル（オペレーター PC 側のみ。ViewerPage では使わない）
  const [realtimeYoloOn, setRealtimeYoloOn] = useState(false)
  const realtimeYolo = useRealtimeYolo(remoteStream, sessionCode, realtimeYoloOn)

  useEffect(() => { connect() }, [connect])
  // health callback へ変化を通知
  useEffect(() => {
    onHealthChange?.({ wsConnected, connectionState, turnInUse })
  }, [wsConnected, connectionState, turnInUse, onHealthChange])
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
      await apiDelete(`/sessions/${sessionCode}/devices`, { 'X-Idempotency-Key': newIdempotencyKey() })
    } catch { /* 失敗は無視 */ }
    fetchDevices()
  }

  const handleDeleteDevice = async (p: SessionParticipant) => {
    try {
      await apiDelete(`/sessions/${sessionCode}/devices/${p.id}`, { 'X-Idempotency-Key': newIdempotencyKey() })
    } catch { /* 失敗は無視 */ }
    fetchDevices()
  }

  const handleApprove = (p: SessionParticipant) => post(`/devices/${p.id}/approve`)
  const handleReject  = (p: SessionParticipant) => post(`/devices/${p.id}/reject`)
  const MAX_ACTIVE_CAMERAS = 4

  const handleActivateCamera = async (p: SessionParticipant) => {
    // 最大4台まで同時 active_camera を許可。上限到達時は手動で降格を促す。
    const activeCount = participants.filter((x) => x.connection_role === 'active_camera').length
    if (activeCount >= MAX_ACTIVE_CAMERAS && p.connection_role !== 'active_camera') {
      setHandoffTarget(p)  // 上限超過時のみ確認ダイアログ（降格先を選ぶ）
      return
    }
    await post(`/devices/${p.id}/activate-camera`)
    requestCamera(p.id)
  }

  const confirmHandoff = async () => {
    // 上限超過時: 既存の active_camera を 1 台降格してから昇格する
    if (!handoffTarget) return
    const actives = participants.filter((x) => x.connection_role === 'active_camera')
    if (actives.length >= MAX_ACTIVE_CAMERAS) {
      // 最初の active を降格
      const oldest = actives[0]
      await post(`/devices/${oldest.id}/deactivate-camera`)
      sendMessage({ type: 'camera_deactivate', target_participant_id: oldest.id })
    }
    await post(`/devices/${handoffTarget.id}/activate-camera`)
    requestCamera(handoffTarget.id)
    setHandoffTarget(null)
  }
  const handleDeactivate = async (p: SessionParticipant) => {
    await post(`/devices/${p.id}/deactivate-camera`)
    sendMessage({ type: 'camera_deactivate', target_participant_id: p.id })
  }
  const handleMakeCandidate  = (p: SessionParticipant) => post(`/devices/${p.id}/set-role`, { connection_role: 'camera_candidate' })
  const handleAllowVideo     = (p: SessionParticipant) => post(`/devices/${p.id}/set-viewer-permission`, { viewer_permission: 'allowed' })
  const handleBlockVideo     = (p: SessionParticipant) => post(`/devices/${p.id}/set-viewer-permission`, { viewer_permission: 'blocked' })

  const doSelectLocalSource = async (src: LocalCameraSource) => {
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

  const handleSelectLocalSource = async (src: LocalCameraSource) => {
    // If a remote camera is currently active, confirm switching to local
    const activeRemote = participants.find((x) => x.connection_role === 'active_camera')
    if (activeRemote && remoteStream) {
      setLocalSwitchPending(src)
      return
    }
    await doSelectLocalSource(src)
  }

  const confirmLocalSwitch = async () => {
    if (!localSwitchPending) return
    const activeRemote = participants.find((x) => x.connection_role === 'active_camera')
    if (activeRemote) {
      await post(`/devices/${activeRemote.id}/deactivate-camera`)
      sendMessage({ type: 'camera_deactivate', target_participant_id: activeRemote.id })
    }
    await doSelectLocalSource(localSwitchPending)
    setLocalSwitchPending(null)
  }
  const handleStopLocal = () => {
    localStream?.getTracks().forEach((t) => t.stop())
    setLocalStream(null)
    setLocalActiveId(null)
    setLocalCameraError(null)
    // onLocalStreamはuseEffectで自動発火（localStream→null）
  }

  // ─── スタイル ────────────────────────────────────────────────────────
  // NOTE: トークンはテーマ (data-theme) に応じて自動的に値が切り替わるため、
  // isLight による分岐は不要になったが、他コンポーネントへ渡す props 形状は維持する。

  const panelBg = 'bg-[var(--ss-surface-1)] border border-[var(--ss-border)] shadow-card'
  const titleColor = 'text-[var(--ss-t1)]'
  const subColor = 'text-[var(--ss-t3)]'
  const rowBg = 'bg-[var(--ss-surface-2)] hover:bg-[var(--ss-surface-3)]'
  const divider = 'border-[var(--ss-border)]'
  const tabActive = 'border-[var(--ss-brand)] text-[var(--ss-brand)]'
  const tabInactive = 'border-transparent text-[var(--ss-t3)] hover:text-[var(--ss-t1)]'

  return (
    <div className={`rounded-ss-lg w-[420px] p-5 max-h-[88vh] overflow-y-auto ${panelBg}`}>
      {/* ヘッダー */}
      <div className="flex items-center justify-between mb-3">
        <p className={`text-sm font-semibold ${titleColor}`}>{t('lan_session.device_manager_title')}</p>
        <div className="flex items-center gap-2">
          <button
            onClick={handlePurgeDisconnected}
            title={t('auto.DeviceManagerPanel.k12')}
            className={`${subColor} hover:text-[var(--ss-bad)] transition-colors duration-base ease-out`}
          >
            <MIcon name="delete" size={14} />
          </button>
          <button onClick={fetchDevices} className={`${subColor}`}>
            <MIcon name="refresh" size={14} className={loading ? 'animate-spin' : ''} />
          </button>
          <button onClick={onClose} className={`${subColor}`}><MIcon name="close" size={16} /></button>
        </div>
      </div>

      {/* タブ */}
      <div className={`flex border-b mb-4 ${divider}`}>
        {(['devices', 'sources'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-3 py-1.5 text-xs font-medium border-b-2 transition-colors duration-base ease-out ${
              activeTab === tab ? tabActive : tabInactive
            }`}
          >
            {tab === 'devices' ? '接続デバイス' : 'ソース管理'}
          </button>
        ))}
      </div>

      {/* ─── リモート診断パネル ── */}
      <div className="mb-3 rounded-ss-md px-3 py-2 space-y-1 text-[10px] bg-[var(--ss-surface-2)] border border-[var(--ss-border)]">
        <p className="text-[9px] font-semibold uppercase tracking-wider mb-1.5 text-[var(--ss-t3)]">{t('auto.DeviceManagerPanel.k3')}</p>

        {/* シグナリング (WS) */}
        <div className="flex items-center gap-1.5">
          <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${wsConnected ? 'bg-[var(--ss-success)]' : wsReconnecting ? 'bg-[var(--ss-warn)] animate-pulse' : 'bg-[var(--ss-t3)]'}`} />
          <span className="text-[var(--ss-t2)]">{t('auto.DeviceManagerPanel.k4')}</span>
          <span className={wsConnected ? 'text-[var(--ss-success)]' : wsReconnecting ? 'text-[var(--ss-warn)]' : 'text-[var(--ss-t3)]'}>
            {wsConnected ? '接続中' : wsReconnecting ? `再接続中 (${wsReconnectCount}/5)` : '未接続'}
          </span>
        </div>

        {/* P2P (WebRTC) */}
        <div className="flex items-center gap-1.5">
          <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
            connectionState === 'connected' ? 'bg-[var(--ss-success)]'
            : connectionState === 'failed' ? 'bg-[var(--ss-bad)]'
            : connectionState === 'connecting' ? 'bg-[var(--ss-warn)] animate-pulse'
            : 'bg-[var(--ss-t3)]'
          }`} />
          <span className="text-[var(--ss-t2)]">{t('auto.DeviceManagerPanel.k5')}</span>
          <span className={
            connectionState === 'connected' ? 'text-[var(--ss-success)]'
            : connectionState === 'failed' ? 'text-[var(--ss-bad)]'
            : 'text-[var(--ss-t3)]'
          }>{connectionState ?? '待機中'}</span>
        </div>

        {/* ICE 収集状態 */}
        {iceGatheringState && (
          <div className="flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full flex-shrink-0 bg-[var(--ss-t3)]" />
            <span className="text-[var(--ss-t2)]">{t('auto.DeviceManagerPanel.k6')}</span>
            <span className="text-[var(--ss-t3)]">{iceGatheringState}</span>
          </div>
        )}

        {/* TURN 使用状況 */}
        <div className="flex items-center gap-1.5">
          <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${turnInUse === true ? 'bg-[var(--ss-brand)]' : 'bg-[var(--ss-t3)]'}`} />
          <span className="text-[var(--ss-t2)]">{t('auto.DeviceManagerPanel.k7')}</span>
          {turnInUse === null
            ? <span className="text-[var(--ss-t3)]">{t('auto.DeviceManagerPanel.k8')}</span>
            : turnInUse
              ? <span className="text-[var(--ss-brand)]">{t('auto.DeviceManagerPanel.k9')}</span>
              : <span className="text-[var(--ss-t3)]">{t('auto.DeviceManagerPanel.k10')}</span>
          }
        </div>
      </div>

      {/* ─── リモートカメラ映像 ── */}
      {remoteStream && (
        <div className="mb-4 relative">
          <div className="flex items-center justify-between mb-1">
            <p className={`text-[10px] ${subColor}`}>
              <span className="inline-block w-2 h-2 rounded-full bg-[var(--ss-bad)] mr-1 animate-pulse" />
              {t('auto.DeviceManagerPanel.remote_receiving', { id: activeParticipantId })}
              {turnInUse === true && <span className="ml-2 text-[var(--ss-brand)]">{t('auto.DeviceManagerPanel.turn')}</span>}
              {turnInUse === false && <span className="ml-2 text-[var(--ss-t3)]">{t('auto.DeviceManagerPanel.p2p')}</span>}
            </p>
            <button
              onClick={() => setRealtimeYoloOn((v) => !v)}
              className={`text-[10px] px-2 py-0.5 rounded-ss-pill border transition-colors duration-base ease-out ${
                realtimeYoloOn
                  ? 'border-[var(--ss-success)] bg-[var(--ss-success-tint)] text-[var(--ss-success)]'
                  : 'border-[var(--ss-border-strong)] text-[var(--ss-t2)] hover:border-[var(--ss-t3)]'
              }`}
              title={t('auto.DeviceManagerPanel.k13')}
            >
              {t('auto.DeviceManagerPanel.realtime_yolo', { state: realtimeYoloOn ? 'ON' : 'OFF' })}
              {realtimeYoloOn && realtimeYolo.inferMs != null && (
                <span className="ml-1 opacity-70">{realtimeYolo.inferMs}ms</span>
              )}
            </button>
          </div>
          <div className="relative">
            <video
              ref={remoteVideoRef}
              autoPlay playsInline muted
              className="w-full rounded-ss-md aspect-video bg-black object-contain"
            />
            <LiveInferenceOverlay
              videoRef={remoteVideoRef}
              sessionCode={sessionCode}
              className="absolute inset-0"
            />
            {realtimeYoloOn && (
              <RealtimeYoloOverlay
                videoRef={remoteVideoRef}
                boxes={realtimeYolo.boxes}
              />
            )}
          </div>
          {realtimeYoloOn && realtimeYolo.error && (
            <p className="text-[10px] text-[var(--ss-bad)] mt-1">{realtimeYolo.error}</p>
          )}
        </div>
      )}

      {/* ─── ローカルカメラ映像 ── */}
      {localStream && (
        <div className="mb-4">
          <div className="flex items-center justify-between mb-1">
            <p className={`text-[10px] ${subColor}`}>
              <span className="inline-block w-2 h-2 rounded-full bg-[var(--ss-success)] mr-1 animate-pulse" />
              {t('auto.DeviceManagerPanel.local_camera')}
            </p>
            <button onClick={handleStopLocal} className="text-xs text-[var(--ss-bad)] hover:opacity-80 transition-colors duration-base ease-out flex items-center gap-1">
              <MIcon name="videocam_off" size={12} />{t('lan_session.local_source_stop')}
            </button>
          </div>
          <video
            ref={localVideoRef}
            autoPlay playsInline muted
            className="w-full rounded-ss-md aspect-video bg-black object-contain"
          />
        </div>
      )}

      {/* ─── タブコンテンツ ── */}

      {activeTab === 'devices' && (
        <>
          {/* 承認待ちバナー */}
          {participants.filter((p) => p.approval_status === 'pending').length > 0 && (
            <div className="mb-3 px-3 py-2 rounded-ss-md border border-[var(--ss-warning-border)] bg-[var(--ss-warn-tint)] flex items-center gap-2">
              <MIcon name="warning" size={12} className="text-[var(--ss-warn)] flex-shrink-0" />
              <p className="text-xs text-[var(--ss-warn)]">
                {t('auto.DeviceManagerPanel.pending_devices')}
              </p>
            </div>
          )}

          {/* グループ別デバイス一覧 */}
          {participants.length === 0 ? (
            <p className={`text-xs text-center py-4 ${subColor}`}>{t('lan_session.no_devices')}</p>
          ) : (
            <DeviceGroupedList
              participants={participants}
              isLight={isLight}
              titleColor={titleColor}
              subColor={subColor}
              rowBg={rowBg}
              divider={divider}
              onApprove={handleApprove}
              onReject={handleReject}
              onActivateCamera={handleActivateCamera}
              onDeactivate={handleDeactivate}
              onRequestCamera={(p) => requestCamera(p.id)}
              onMakeCandidate={handleMakeCandidate}
              onAllowVideo={handleAllowVideo}
              onBlockVideo={handleBlockVideo}
              onDeleteDevice={handleDeleteDevice}
              t={t}
            />
          )}

          {/* ローカルカメラソース */}
          {localSources.length > 0 && (
            <div className={`border-t pt-3 mt-3 ${divider}`}>
              <p className={`text-xs font-medium mb-2 ${titleColor}`}>{t('lan_session.local_sources_label')}</p>
              {localCameraError && (
                <p className="text-[10px] text-[var(--ss-bad)] mb-2 flex items-center gap-1">
                  <MIcon name="cancel" size={10} />{localCameraError}
                </p>
              )}
              <div className="space-y-1.5">
                {localSources.map((src) => (
                  <div key={src.deviceId} className={`flex items-center gap-2 rounded-ss-md px-3 py-2 ${rowBg}`}>
                    <MIcon name="photo_camera" size={12} className={subColor} />
                    <span className={`flex-1 text-xs truncate ${titleColor}`}>{src.label}</span>
                    <span className={`text-[10px] ${subColor}`}>
                      {src.type === 'usb' ? t('lan_session.source_type_usb') : src.type === 'builtin' ? t('lan_session.source_type_builtin') : ''}
                    </span>
                    {localActiveId === src.deviceId ? (
                      <button onClick={handleStopLocal}
                        className="text-[10px] px-2 py-0.5 rounded-ss-sm bg-[var(--ss-surface-3)] hover:bg-[var(--ss-border-strong)] transition-colors duration-base ease-out text-[var(--ss-t1)]">
                        {t('lan_session.local_source_stop')}
                      </button>
                    ) : (
                      <button onClick={() => handleSelectLocalSource(src)}
                        className="text-[10px] px-2 py-0.5 rounded-ss-sm bg-[var(--ss-brand)] hover:bg-[var(--ss-brand-hover)] transition-colors duration-base ease-out text-white">
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

      {/* ─── ハンドオフ確認ダイアログ ── */}
      {handoffTarget && (
        <div className="fixed inset-0 z-60 flex items-center justify-center bg-black/60" onClick={() => setHandoffTarget(null)}>
          <div
            className="rounded-ss-lg p-5 w-72 shadow-pop bg-[var(--ss-surface-1)] border border-[var(--ss-border)]"
            onClick={(e) => e.stopPropagation()}
          >
            <p className={`text-sm font-semibold mb-1 ${titleColor}`}>{t('handoff.confirm_title')}</p>
            <p className={`text-xs mb-4 ${subColor}`}>
              {t('handoff.confirm_body')}<br />
              <span className="font-medium">{handoffTarget.device_name ?? `デバイス #${handoffTarget.id}`}</span>
            </p>
            <div className="flex gap-2">
              <button onClick={confirmHandoff} className="flex-1 py-2 rounded-ss-md bg-[var(--ss-bad)] hover:opacity-90 transition-colors duration-base ease-out text-white text-sm">
                {t('handoff.confirm_ok')}
              </button>
              <button onClick={() => setHandoffTarget(null)} className="flex-1 py-2 rounded-ss-md text-sm bg-[var(--ss-surface-2)] hover:bg-[var(--ss-surface-3)] transition-colors duration-base ease-out text-[var(--ss-t1)]">
                {t('handoff.confirm_cancel')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ─── ローカル切替確認ダイアログ ── */}
      {localSwitchPending && (
        <div className="fixed inset-0 z-60 flex items-center justify-center bg-black/60" onClick={() => setLocalSwitchPending(null)}>
          <div
            className="rounded-ss-lg p-5 w-72 shadow-pop bg-[var(--ss-surface-1)] border border-[var(--ss-border)]"
            onClick={(e) => e.stopPropagation()}
          >
            <p className={`text-sm font-semibold mb-1 ${titleColor}`}>{t('handoff.local_switch_confirm')}</p>
            <p className={`text-xs mb-4 ${subColor}`}>{localSwitchPending.label}</p>
            <div className="flex gap-2">
              <button onClick={confirmLocalSwitch} className="flex-1 py-2 rounded-ss-md bg-[var(--ss-brand)] hover:bg-[var(--ss-brand-hover)] transition-colors duration-base ease-out text-white text-sm">
                {t('handoff.local_switch_ok')}
              </button>
              <button onClick={() => setLocalSwitchPending(null)} className="flex-1 py-2 rounded-ss-md text-sm bg-[var(--ss-surface-2)] hover:bg-[var(--ss-surface-3)] transition-colors duration-base ease-out text-[var(--ss-t1)]">
                {t('handoff.local_switch_cancel')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
