/**
 * カメラ signaling の受信側 — 複数カメラ対応。
 *
 * 旧実装 (DeviceManagerPanel 内の useWebRTCReceiver) は RTCPeerConnection を
 * 1 本しか持たず、`webrtc_offer` を受けるたびに既存を close して差し替えていた。
 * UI は「アクティブカメラ 4 台」を、サーバは 10 台を許すのに、**実際には
 * 同時 1 台しか成立していなかった**。2 台目を有効化すると 1 台目が黙って落ち、
 * 落とされた端末には何も通知されないのでカメラは点いたまま送信を続けていた。
 *
 * ここでは stream_id ごとに PeerConnection を持つ。stream_id はサーバが接続
 * ごとに採番するので、「同じ端末の新しい映像」と「前の映像の残骸」を区別できる。
 *
 * あわせて直すもの:
 *   - viewer が映像確立前に入ると `viewer_joined` が捨てられ、後から映像が
 *     始まっても再オファーされず永久に待機していた → 保留して drain する
 *   - 同じ viewer が再接続すると旧 PeerConnection を close せず Map を
 *     上書きしていた → 置換前に閉じる
 *   - `ws.onmessage = async` で受信が直列化されず、offer 処理の await 中に
 *     届いた ICE が remote description 未設定の PC に渡って捨てられていた
 *     → 処理を直列化し、remote description 前の ICE は貯める
 */
import { useCallback, useEffect, useRef, useState } from 'react'

import { apiGet } from '@/api/client'
import { cameraWsUrl } from '@/utils/cameraWs'

export interface CameraStream {
  streamId: string
  participantId: string
  stream: MediaStream
}

interface IngressPeer {
  participantId: string
  pc: RTCPeerConnection
  /** remote description 適用前に届いた ICE を貯める */
  pendingIce: RTCIceCandidateInit[]
  remoteReady: boolean
}

interface EgressPeer {
  pc: RTCPeerConnection
  streamId: string
  pendingIce: RTCIceCandidateInit[]
  remoteReady: boolean
}

const DEFAULT_ICE: RTCIceServer[] = [{ urls: 'stun:stun.l.google.com:19302' }]
const RECONNECT_DELAY_MS = 5_000

export interface CameraHubState {
  streams: CameraStream[]
  wsConnected: boolean
  reconnecting: boolean
  reconnectCount: number
  connectionStates: Record<string, RTCPeerConnectionState>
  turnInUse: boolean | null
  connect: () => Promise<void>
  disconnect: () => void
  requestCamera: (streamIdOrParticipant: string | number) => void
  sendMessage: (msg: object) => void
}

export function useCameraHub(sessionCode: string): CameraHubState {
  const wsRef = useRef<WebSocket | null>(null)
  const ingressRef = useRef<Map<string, IngressPeer>>(new Map())
  const egressRef = useRef<Map<string, EgressPeer>>(new Map())
  /** 映像がまだ無いうちに来た viewer。stream ができたら drain する */
  const pendingViewersRef = useRef<Set<string>>(new Set())
  const iceServersRef = useRef<RTCIceServer[]>(DEFAULT_ICE)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const reconnectCountRef = useRef(0)
  const manualDisconnectRef = useRef(false)
  /** 受信処理を直列化する。並行に走ると ICE と offer が競合する */
  const queueRef = useRef<Promise<void>>(Promise.resolve())
  const statsTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const [streams, setStreams] = useState<CameraStream[]>([])
  const [wsConnected, setWsConnected] = useState(false)
  const [reconnecting, setReconnecting] = useState(false)
  const [reconnectCount, setReconnectCount] = useState(0)
  const [connectionStates, setConnectionStates] =
    useState<Record<string, RTCPeerConnectionState>>({})
  const [turnInUse, setTurnInUse] = useState<boolean | null>(null)

  const publish = useCallback(() => {
    const list: CameraStream[] = []
    ingressRef.current.forEach((peer, streamId) => {
      const s = peer.pc.getReceivers()
        .map((r) => r.track)
        .filter((t): t is MediaStreamTrack => !!t)
      if (s.length) list.push({ streamId, participantId: peer.participantId, stream: new MediaStream(s) })
    })
    setStreams(list)
  }, [])

  const send = useCallback((msg: object) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg))
    }
  }, [])

  // ─── ICE のバッファリング ─────────────────────────────────────────────────
  const addIce = useCallback(async (
    holder: IngressPeer | EgressPeer, init: RTCIceCandidateInit,
  ) => {
    if (!holder.remoteReady) {
      // remote description 前に渡すと弾かれる。適用後にまとめて入れる
      holder.pendingIce.push(init)
      return
    }
    await holder.pc.addIceCandidate(init).catch(() => { /* 個別失敗は許容 */ })
  }, [])

  const drainIce = useCallback(async (holder: IngressPeer | EgressPeer) => {
    holder.remoteReady = true
    const queued = holder.pendingIce.splice(0)
    for (const init of queued) {
      await holder.pc.addIceCandidate(init).catch(() => { /* 同上 */ })
    }
  }, [])

  // ─── viewer への配信 ──────────────────────────────────────────────────────
  const offerToViewer = useCallback(async (viewerId: string, streamId: string) => {
    const ingress = ingressRef.current.get(streamId)
    if (!ingress) return
    const tracks = ingress.pc.getReceivers().map((r) => r.track)
      .filter((t): t is MediaStreamTrack => !!t)
    if (!tracks.length) return

    // 同じ viewer の旧 PeerConnection は必ず閉じてから置き換える
    const previous = egressRef.current.get(viewerId)
    if (previous) {
      previous.pc.close()
      egressRef.current.delete(viewerId)
    }

    const pc = new RTCPeerConnection({ iceServers: iceServersRef.current })
    const holder: EgressPeer = { pc, streamId, pendingIce: [], remoteReady: false }
    egressRef.current.set(viewerId, holder)
    const outbound = new MediaStream(tracks)
    tracks.forEach((t) => pc.addTrack(t, outbound))
    pc.onicecandidate = (e) => {
      if (e.candidate) {
        send({
          type: 'viewer_ice_candidate', viewer_id: viewerId,
          candidate: e.candidate.candidate, sdp_mid: e.candidate.sdpMid,
          sdp_m_line_index: e.candidate.sdpMLineIndex,
        })
      }
    }
    const offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    send({ type: 'viewer_webrtc_offer', viewer_id: viewerId, sdp: offer.sdp })
  }, [send])

  const drainPendingViewers = useCallback(async (streamId: string) => {
    const waiting = Array.from(pendingViewersRef.current)
    pendingViewersRef.current.clear()
    for (const viewerId of waiting) {
      await offerToViewer(viewerId, streamId)
    }
  }, [offerToViewer])

  // ─── カメラからの offer ───────────────────────────────────────────────────
  const acceptCameraOffer = useCallback(async (msg: {
    stream_id?: string; participant_id?: string; sdp: string
  }) => {
    const streamId = String(msg.stream_id ?? msg.participant_id ?? '')
    if (!streamId) return
    const participantId = String(msg.participant_id ?? '')

    // 同じ stream の再交渉なら差し替える。**他の stream には触らない**
    const existing = ingressRef.current.get(streamId)
    if (existing) {
      existing.pc.close()
      ingressRef.current.delete(streamId)
    }

    const pc = new RTCPeerConnection({ iceServers: iceServersRef.current })
    const holder: IngressPeer = { participantId, pc, pendingIce: [], remoteReady: false }
    ingressRef.current.set(streamId, holder)

    pc.onconnectionstatechange = () => {
      setConnectionStates((prev) => ({ ...prev, [streamId]: pc.connectionState }))
      if (pc.connectionState === 'failed' || pc.connectionState === 'closed') {
        publish()
      }
    }
    pc.ontrack = () => {
      publish()
      void drainPendingViewers(streamId)
    }
    pc.onicecandidate = (e) => {
      if (e.candidate) {
        send({
          type: 'ice_candidate', stream_id: streamId,
          target_participant_id: participantId,
          candidate: e.candidate.candidate, sdp_mid: e.candidate.sdpMid,
          sdp_m_line_index: e.candidate.sdpMLineIndex,
        })
      }
    }

    await pc.setRemoteDescription({ type: 'offer', sdp: msg.sdp })
    await drainIce(holder)
    const answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    send({
      type: 'webrtc_answer', stream_id: streamId,
      target_participant_id: participantId, sdp: answer.sdp,
    })
  }, [drainIce, drainPendingViewers, publish, send])

  const closeStream = useCallback((streamId: string) => {
    const peer = ingressRef.current.get(streamId)
    if (!peer) return
    peer.pc.close()
    ingressRef.current.delete(streamId)
    // その stream を見ていた viewer も畳む
    egressRef.current.forEach((eg, viewerId) => {
      if (eg.streamId === streamId) {
        eg.pc.close()
        egressRef.current.delete(viewerId)
      }
    })
    setConnectionStates((prev) => {
      const next = { ...prev }
      delete next[streamId]
      return next
    })
    publish()
  }, [publish])

  // ─── メッセージ処理 (直列) ────────────────────────────────────────────────
  const handle = useCallback(async (msg: Record<string, unknown>) => {
    const type = msg.type as string
    if (type === 'webrtc_offer') {
      await acceptCameraOffer(msg as never)
    } else if (type === 'ice_candidate') {
      const streamId = String(msg.stream_id ?? msg.participant_id ?? '')
      const peer = ingressRef.current.get(streamId)
      if (peer) {
        await addIce(peer, {
          candidate: msg.candidate as string,
          sdpMid: msg.sdp_mid as string,
          sdpMLineIndex: msg.sdp_m_line_index as number,
        })
      }
    } else if (type === 'camera_stream_ended' || type === 'camera_stop') {
      closeStream(String(msg.stream_id ?? msg.participant_id ?? ''))
    } else if (type === 'viewer_joined') {
      const viewerId = String(msg.viewer_id)
      const first = ingressRef.current.keys().next()
      if (first.done) {
        // まだ映像が無い。捨てずに保留し、stream ができたら配る
        pendingViewersRef.current.add(viewerId)
      } else {
        await offerToViewer(viewerId, first.value)
      }
    } else if (type === 'viewer_webrtc_answer') {
      const holder = egressRef.current.get(String(msg.viewer_id))
      if (holder) {
        await holder.pc.setRemoteDescription({ type: 'answer', sdp: msg.sdp as string })
        await drainIce(holder)
      }
    } else if (type === 'viewer_ice_candidate') {
      const holder = egressRef.current.get(String(msg.viewer_id))
      if (holder) {
        await addIce(holder, {
          candidate: msg.candidate as string,
          sdpMid: msg.sdp_mid as string,
          sdpMLineIndex: msg.sdp_m_line_index as number,
        })
      }
    } else if (type === 'viewer_left') {
      const viewerId = String(msg.viewer_id)
      pendingViewersRef.current.delete(viewerId)
      egressRef.current.get(viewerId)?.pc.close()
      egressRef.current.delete(viewerId)
    }
  }, [acceptCameraOffer, addIce, closeStream, drainIce, offerToViewer])

  // ─── TURN 利用状況 ────────────────────────────────────────────────────────
  const startStatsPolling = useCallback(() => {
    if (statsTimerRef.current) return
    statsTimerRef.current = setInterval(async () => {
      let relay = false
      for (const peer of ingressRef.current.values()) {
        try {
          const stats = await peer.pc.getStats()
          stats.forEach((report) => {
            if (report.type === 'candidate-pair' && report.state === 'succeeded') {
              stats.forEach((r) => {
                if (r.id === report.localCandidateId && r.candidateType === 'relay') relay = true
              })
            }
          })
        } catch { /* ignore */ }
      }
      setTurnInUse(ingressRef.current.size ? relay : null)
    }, 5000)
  }, [])

  const disconnect = useCallback(() => {
    manualDisconnectRef.current = true
    if (reconnectTimerRef.current) { clearTimeout(reconnectTimerRef.current); reconnectTimerRef.current = null }
    if (statsTimerRef.current) { clearInterval(statsTimerRef.current); statsTimerRef.current = null }
    reconnectCountRef.current = 0
    ingressRef.current.forEach((p) => p.pc.close())
    ingressRef.current.clear()
    egressRef.current.forEach((p) => p.pc.close())
    egressRef.current.clear()
    pendingViewersRef.current.clear()
    wsRef.current?.close()
    wsRef.current = null
    setStreams([])
    setConnectionStates({})
    setWsConnected(false)
    setReconnecting(false)
    setReconnectCount(0)
    setTurnInUse(null)
  }, [])

  const connect = useCallback(async () => {
    if (wsRef.current) return
    manualDisconnectRef.current = false
    try {
      const cfg = await apiGet<{ success: boolean; data: { ice_servers: RTCIceServer[] } }>(
        '/webrtc/ice-config')
      if (cfg.success && cfg.data.ice_servers.length) iceServersRef.current = cfg.data.ice_servers
    } catch { /* STUN のまま続行 */ }

    let ws: WebSocket
    try {
      ws = new WebSocket(cameraWsUrl(sessionCode, { role: 'operator' }))
    } catch { return }
    wsRef.current = ws

    ws.onopen = () => {
      setWsConnected(true)
      setReconnecting(false)
      setReconnectCount(0)
      reconnectCountRef.current = 0
      startStatsPolling()
    }
    ws.onclose = () => {
      wsRef.current = null
      setWsConnected(false)
      if (manualDisconnectRef.current) return
      // 旧実装は 5 回で恒久停止し UI に再開手段が無かった。
      // 試合中の瞬断でシグナリングが死ぬので、指数バックオフで粘る。
      const next = reconnectCountRef.current + 1
      reconnectCountRef.current = next
      setReconnectCount(next)
      setReconnecting(true)
      const delay = Math.min(RECONNECT_DELAY_MS * 2 ** Math.min(next - 1, 4), 60_000)
      reconnectTimerRef.current = setTimeout(() => { void connect() }, delay)
    }
    ws.onmessage = (event) => {
      // 直列化する。並行に走らせると offer の await 中に ICE が入り込み、
      // remote description 未設定の PC に渡って黙って捨てられる
      queueRef.current = queueRef.current.then(async () => {
        try {
          await handle(JSON.parse(event.data))
        } catch { /* 個別メッセージの失敗で列を止めない */ }
      })
    }
  }, [sessionCode, handle, startStatsPolling])

  useEffect(() => () => { disconnect() }, [disconnect])

  return {
    streams, wsConnected, reconnecting, reconnectCount,
    connectionStates, turnInUse, connect, disconnect,
    requestCamera: (target) => send({
      type: 'camera_request',
      ...(typeof target === 'string' && target.length > 20
        ? { stream_id: target }
        : { target_participant_id: target }),
    }),
    sendMessage: send,
  }
}
