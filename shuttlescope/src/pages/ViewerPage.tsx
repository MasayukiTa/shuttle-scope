/**
 * リモートビューワーページ — PC / タブレット向け
 *
 * オペレーター PC が iOS カメラから受けた映像ストリームを
 * WebRTC 経由で転送受信して表示する。
 *
 * 接続フロー:
 *   join → POST /sessions/{code}/join (role=viewer)
 *        → WS /ws/camera/{code}?role=viewer&vid={pid}
 *        → operator が viewer_webrtc_offer を送信
 *        → RTCPeerConnection で受信・表示
 *
 * 再接続: WS 切断後 5 秒で自動再接続（最大 5 回）
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams, useLocation } from 'react-router-dom'
import { Eye, WifiOff, Loader2, CheckCircle2, XCircle, Video } from 'lucide-react'
import { apiPost, apiGet } from '@/api/client'
import { useDeviceHeartbeat } from '@/hooks/useDeviceHeartbeat'

type ViewerState = 'join' | 'connecting' | 'waiting' | 'receiving' | 'error'

const MAX_RECONNECT = 5
const RECONNECT_DELAY_MS = 5_000
const VIEWER_NAME_KEY = 'ss_viewer_name'

export function ViewerPage() {
  const { sessionCode: paramCode } = useParams<{ sessionCode: string }>()
  const { search } = useLocation()
  const pwdParam = new URLSearchParams(search).get('pwd') ?? ''

  const [viewerState, setViewerState] = useState<ViewerState>(paramCode ? 'connecting' : 'join')
  const [form, setForm] = useState({
    sessionCode: paramCode ?? '',
    password: '',
    viewerName: localStorage.getItem(VIEWER_NAME_KEY) || 'ビューワー',
  })
  const [errorMsg, setErrorMsg] = useState('')
  const [reconnectCount, setReconnectCount] = useState(0)
  const [participantId, setParticipantId] = useState<number | null>(null)
  const [activeSessionCode, setActiveSessionCode] = useState<string>(paramCode ?? '')

  const wsRef = useRef<WebSocket | null>(null)
  const pcRef = useRef<RTCPeerConnection | null>(null)
  const videoRef = useRef<HTMLVideoElement>(null)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const reconnectCountRef = useRef(0)
  const viewerStateRef = useRef<ViewerState>(viewerState)
  const savedCodeRef = useRef(paramCode ?? '')
  const savedPidRef = useRef<number | null>(null)
  const savedPasswordRef = useRef('')
  const savedNameRef = useRef('')

  useEffect(() => { viewerStateRef.current = viewerState }, [viewerState])

  // ─── ハートビート ─────────────────────────────────────────────────────────
  useDeviceHeartbeat(
    viewerState === 'waiting' || viewerState === 'receiving' ? activeSessionCode : null,
    participantId,
  )

  // ─── 再接続スケジュール ───────────────────────────────────────────────────
  const scheduleReconnect = useCallback((code: string, pid: number) => {
    const count = reconnectCountRef.current + 1
    if (count > MAX_RECONNECT) {
      setViewerState('error')
      setErrorMsg('接続が失われました。再試行してください。')
      return
    }
    reconnectCountRef.current = count
    setReconnectCount(count)
    setViewerState('connecting')
    reconnectTimerRef.current = setTimeout(() => {
      connectWs(code, pid) // eslint-disable-line
    }, RECONNECT_DELAY_MS)
  }, []) // connectWs is defined below

  // ─── WebSocket 接続 ───────────────────────────────────────────────────────
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const connectWs = useCallback((code: string, pid: number) => {
    if (wsRef.current) {
      wsRef.current.onclose = null
      wsRef.current.close()
      wsRef.current = null
    }

    const isElectron = window.location.protocol === 'file:'
    const isHttps = window.location.protocol === 'https:'
    const wsProto = isHttps ? 'wss' : 'ws'
    const wsHost = isElectron
      ? 'localhost:8765'
      : isHttps
        ? window.location.host
        : `${window.location.hostname}:8765`
    const wsUrl = `${wsProto}://${wsHost}/ws/camera/${code}?role=viewer&vid=${pid}`
    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onopen = () => {
      reconnectCountRef.current = 0
      setReconnectCount(0)
      setViewerState('waiting')
    }

    ws.onmessage = async (event) => {
      try {
        const msg = JSON.parse(event.data)

        if (msg.type === 'viewer_webrtc_offer') {
          // ICE config 取得（TURN 含む）
          let iceServers: RTCIceServer[] = [{ urls: 'stun:stun.l.google.com:19302' }]
          try {
            const iceCfg = await apiGet<{ success: boolean; data: { ice_servers: RTCIceServer[] } }>('/webrtc/ice-config')
            if (iceCfg.success && iceCfg.data.ice_servers.length > 0) {
              iceServers = iceCfg.data.ice_servers
            }
          } catch { /* STUN フォールバック */ }

          // 既存 PC クローズ（ハンドオフ安全化）
          if (pcRef.current) { pcRef.current.close(); pcRef.current = null }

          const pc = new RTCPeerConnection({ iceServers })
          pcRef.current = pc

          pc.ontrack = (e) => {
            if (e.streams[0]) {
              if (videoRef.current) videoRef.current.srcObject = e.streams[0]
              setViewerState('receiving')
            }
          }

          pc.onicecandidate = (e) => {
            if (e.candidate && ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify({
                type: 'viewer_ice_candidate',
                viewer_id: pid,
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
            type: 'viewer_webrtc_answer',
            viewer_id: pid,
            sdp: answer.sdp,
          }))

        } else if (msg.type === 'viewer_ice_candidate' && pcRef.current) {
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
      const st = viewerStateRef.current
      if (st === 'waiting' || st === 'receiving') {
        scheduleReconnect(code, pid)
      }
    }
  }, [scheduleReconnect])

  // ─── セッション参加 ───────────────────────────────────────────────────────
  const joinSession = useCallback(async (code: string, password: string, viewerName: string) => {
    setViewerState('connecting')
    setErrorMsg('')
    const name = viewerName.trim() || localStorage.getItem(VIEWER_NAME_KEY) || 'ビューワー'
    localStorage.setItem(VIEWER_NAME_KEY, name)
    savedCodeRef.current = code
    savedPasswordRef.current = password
    savedNameRef.current = name

    try {
      const res = await apiPost<{
        success: boolean
        data: { participant_id: number; session_code: string }
      }>(`/sessions/${code}/join`, {
        role: 'viewer',
        device_name: name,
        device_type: 'pc',
        session_password: password || undefined,
      })
      if (!res.success) throw new Error('join failed')
      const pid = res.data.participant_id
      setParticipantId(pid)
      savedPidRef.current = pid
      setActiveSessionCode(code)
      reconnectCountRef.current = 0
      connectWs(code, pid)
    } catch (err: any) {
      const status = err?.status
      if (status === 401) setErrorMsg('セッションコードまたはパスワードが正しくありません。')
      else if (status === 404) setErrorMsg('セッションが見つかりません。コードを確認してください。')
      else setErrorMsg('接続に失敗しました。ネットワークを確認してください。')
      setViewerState('join')
    }
  }, [connectWs])

  // URL からセッションコードが渡された場合は直接参加
  useEffect(() => {
    if (paramCode && viewerState === 'connecting') {
      if (pwdParam) {
        joinSession(paramCode, pwdParam, localStorage.getItem(VIEWER_NAME_KEY) || 'ビューワー')
      } else {
        setErrorMsg('QRコードを再生成するか、下のフォームにパスワードを入力してください。')
        setViewerState('join')
      }
    }
  }, []) // eslint-disable-line

  // アンマウント時クリーンアップ
  useEffect(() => {
    return () => {
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
      pcRef.current?.close()
      wsRef.current?.onclose && (wsRef.current.onclose = null)
      wsRef.current?.close()
    }
  }, [])

  // ─── レンダリング ──────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-gray-900 text-white flex flex-col items-center justify-center p-4">
      {/* ロゴ */}
      <div className="mb-4 text-center">
        <div className="inline-flex items-center gap-2 text-blue-400 mb-1">
          <Eye size={24} />
          <span className="text-lg font-bold">ShuttleScope</span>
        </div>
        <p className="text-gray-400 text-sm">リモートビューワー</p>
        <p className="text-gray-600 text-xs mt-1">タブレット・PC で最適な映像視聴が可能です</p>
      </div>

      {/* ─── State: join ── */}
      {(viewerState === 'join' || (viewerState === 'connecting' && !paramCode)) && (
        <div className="w-full max-w-sm bg-gray-800 rounded-xl p-5 shadow-2xl">
          <div className="space-y-3">
            <div>
              <label className="block text-xs text-gray-400 mb-1">セッションコード</label>
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
              <label className="block text-xs text-gray-400 mb-1">パスワード</label>
              <input
                type="password"
                value={form.password}
                onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
                className="w-full bg-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">ビューワー名</label>
              <input
                type="text"
                value={form.viewerName}
                onChange={(e) => setForm((f) => ({ ...f, viewerName: e.target.value }))}
                placeholder="例: コーチPC"
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
              onClick={() => joinSession(form.sessionCode, form.password, form.viewerName)}
              disabled={!form.sessionCode}
              className="w-full py-2.5 rounded-lg bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-sm font-medium"
            >
              参加する
            </button>
          </div>
        </div>
      )}

      {/* ─── State: connecting ── */}
      {viewerState === 'connecting' && paramCode && (
        <div className="text-center">
          <Loader2 size={40} className="animate-spin text-blue-400 mx-auto mb-3" />
          <p className="text-gray-300 text-sm">
            {reconnectCount > 0
              ? `再接続中... (${reconnectCount}/${MAX_RECONNECT})`
              : 'セッションに接続中...'}
          </p>
        </div>
      )}

      {/* ─── State: waiting ── */}
      {viewerState === 'waiting' && (
        <div className="w-full max-w-sm bg-gray-800 rounded-xl p-8 text-center shadow-2xl">
          <div className="w-16 h-16 rounded-full bg-blue-900/50 flex items-center justify-center mx-auto mb-4">
            <Eye size={28} className="text-blue-400" />
          </div>
          <p className="text-lg font-semibold mb-2">映像待機中</p>
          <p className="text-gray-400 text-sm leading-relaxed">
            オペレーターが映像を開始するまでお待ちください。
          </p>
          <div className="mt-4 flex items-center justify-center gap-1.5 text-green-400 text-xs">
            <CheckCircle2 size={14} />
            接続済み
            {reconnectCount > 0 && (
              <span className="text-gray-500 ml-1">(再接続 {reconnectCount} 回)</span>
            )}
          </div>
          <p className="mt-4 text-gray-600 text-xs">
            タブレット・PC で映像を受信できます。スマートフォンは要約表示専用です。
          </p>
        </div>
      )}

      {/* ─── State: receiving ── */}
      {viewerState === 'receiving' && (
        <div className="w-full max-w-2xl flex flex-col items-center">
          <div className="relative w-full rounded-xl overflow-hidden bg-black aspect-video shadow-2xl">
            <video
              ref={videoRef}
              autoPlay
              playsInline
              className="w-full h-full object-contain"
            />
            <div className="absolute top-2 left-2 flex items-center gap-1.5 bg-red-600 text-white text-xs px-2 py-0.5 rounded-full">
              <span className="w-1.5 h-1.5 rounded-full bg-white animate-pulse" />
              LIVE
            </div>
          </div>
          <div className="mt-3 flex items-center gap-2 text-xs text-gray-400">
            <Video size={12} />
            <span>受信中</span>
            {activeSessionCode && (
              <span className="font-mono text-gray-500">#{activeSessionCode}</span>
            )}
          </div>
        </div>
      )}

      {/* ─── State: error ── */}
      {viewerState === 'error' && (
        <div className="w-full max-w-sm text-center">
          <div className="bg-gray-800 rounded-xl p-6 shadow-2xl border border-red-500/40">
            <WifiOff size={36} className="text-red-400 mx-auto mb-3" />
            <p className="text-sm text-gray-300 mb-4">{errorMsg || '接続に失敗しました。'}</p>
            <div className="flex gap-2 justify-center">
              <button
                onClick={() => {
                  reconnectCountRef.current = 0
                  setReconnectCount(0)
                  const code = savedCodeRef.current
                  const pid = savedPidRef.current
                  if (code && pid) {
                    setViewerState('connecting')
                    connectWs(code, pid)
                  } else {
                    setViewerState('join')
                    setErrorMsg('')
                  }
                }}
                className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-sm"
              >
                もう一度試す
              </button>
              <button
                onClick={() => { setViewerState('join'); setErrorMsg('') }}
                className="px-4 py-2 rounded-lg bg-gray-700 hover:bg-gray-600 text-sm text-gray-300"
              >
                最初から
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
