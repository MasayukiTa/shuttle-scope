/**
 * カメラ送信ページ — iOS / タブレット向け
 *
 * State 遷移:
 *   join → connecting → A（待機） → B（確認） → C（送信中） → error
 *
 * T16 改善:
 *   - セッション ID + ロール表示（全状態）
 *   - useDeviceHeartbeat フック統合
 *   - 切断後自動再接続（5 秒後リトライ × 3 回）
 *   - RTCPeerConnection.getStats() ネットワーク品質ヒント
 *   - navigator.getBattery() バッテリー残量表示
 *   - 非技術ユーザー向け丁寧な状態テキスト
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams, useLocation } from 'react-router-dom'
import {
  Camera, WifiOff, Loader2, CheckCircle2, XCircle, VideoOff,
  BatteryFull, BatteryMedium, BatteryLow, Wifi, WifiZero, Pencil, Check,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { apiPost, apiGet } from '@/api/client'
import { useDeviceHeartbeat } from '@/hooks/useDeviceHeartbeat'

type SenderState = 'join' | 'connecting' | 'state_a' | 'state_b' | 'state_c' | 'error'

interface JoinForm {
  sessionCode: string
  password: string
  deviceName: string
}

// バッテリー API 型（型定義がない環境向け）
interface BatteryManager {
  level: number
  charging: boolean
  addEventListener: (event: string, cb: () => void) => void
  removeEventListener: (event: string, cb: () => void) => void
}

function getDeviceType(): string {
  const ua = navigator.userAgent
  if (/iPad/.test(ua)) return 'ipad'
  if (/iPhone/.test(ua)) return 'iphone'
  return 'pc'
}

function getDeviceTypeLabel(): string {
  const ua = navigator.userAgent
  if (/iPad/.test(ua)) return 'iPad'
  if (/iPhone/.test(ua)) return 'iPhone'
  return 'このPC'
}

// ─── バッテリー表示 ──────────────────────────────────────────────────────────

function BatteryIndicator({ level, charging }: { level: number; charging: boolean }) {
  const pct = Math.round(level * 100)
  const Icon = pct > 60 ? BatteryFull : pct > 25 ? BatteryMedium : BatteryLow
  const color = pct > 60 ? 'text-green-400' : pct > 25 ? 'text-yellow-400' : 'text-red-400'
  return (
    <span className={`flex items-center gap-0.5 text-[10px] ${color}`}>
      <Icon size={12} />
      {pct}%{charging ? ' ⚡' : ''}
    </span>
  )
}

// ─── ネットワーク品質表示 ────────────────────────────────────────────────────

function NetworkQualityIndicator({ rttMs }: { rttMs: number | null }) {
  const { t } = useTranslation()
  if (rttMs === null) return null
  const good = rttMs < 80
  const Icon = good ? Wifi : WifiZero
  const color = good ? 'text-green-400' : 'text-yellow-400'
  return (
    <span className={`flex items-center gap-0.5 text-[10px] ${color}`}>
      <Icon size={12} />
      {t('camera_sender.network_quality')} {rttMs}ms
    </span>
  )
}

// ─── セッション情報バッジ ────────────────────────────────────────────────────

function SessionBadge({ sessionCode, role }: { sessionCode: string; role: string }) {
  const { t } = useTranslation()
  return (
    <div className="flex items-center gap-2 text-[10px] text-gray-500 mb-1">
      <span>{t('camera_sender.session_label')}: <span className="font-mono text-gray-400">{sessionCode}</span></span>
      <span>|</span>
      <span>{t('camera_sender.role_display')}: <span className="text-blue-400">{role}</span></span>
    </div>
  )
}

// ─── メインコンポーネント ────────────────────────────────────────────────────

const MAX_RECONNECT = 10
const RECONNECT_DELAY_MS = 5_000
const DEVICE_NAME_KEY = 'ss_device_name'

export function CameraSenderPage() {
  const { sessionCode: paramCode } = useParams<{ sessionCode: string }>()
  const { search } = useLocation()
  // QR URL に埋め込まれたパスワード（?pwd=...）を読み取る
  const pwdParam = new URLSearchParams(search).get('pwd') ?? ''
  const { t } = useTranslation()

  const [senderState, setSenderState] = useState<SenderState>(paramCode ? 'connecting' : 'join')
  const [form, setForm] = useState<JoinForm>({
    sessionCode: paramCode ?? '',
    password: '',
    deviceName: localStorage.getItem(DEVICE_NAME_KEY) || getDeviceTypeLabel(),
  })
  const [errorMsg, setErrorMsg] = useState('')
  // 端末名インライン編集用
  const [editingName, setEditingName] = useState(false)
  const [nameInput, setNameInput] = useState('')
  const [isPortrait, setIsPortrait] = useState(() => window.innerHeight > window.innerWidth)
  const [participantId, setParticipantId] = useState<number | null>(null)
  const [activeSessionCode, setActiveSessionCode] = useState<string>(paramCode ?? '')
  const [reconnectCount, setReconnectCount] = useState(0)
  const [battery, setBattery] = useState<{ level: number; charging: boolean } | null>(null)
  const [rttMs, setRttMs] = useState<number | null>(null)

  const wsRef = useRef<WebSocket | null>(null)
  const pcRef = useRef<RTCPeerConnection | null>(null)
  const localStreamRef = useRef<MediaStream | null>(null)
  const previewRef = useRef<HTMLVideoElement>(null)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const rttTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  // 再接続判定用 ref（stale closure 回避）
  const senderStateRef = useRef<SenderState>(senderState)
  const reconnectCountRef = useRef(0)
  const savedCodeRef = useRef(paramCode ?? '')
  const savedPidRef = useRef<number | null>(null)
  const savedPasswordRef = useRef('')
  const savedDeviceNameRef = useRef('')

  useEffect(() => { senderStateRef.current = senderState }, [senderState])

  // ─── ハートビート ─────────────────────────────────────────────────────────
  useDeviceHeartbeat(
    senderState === 'state_a' || senderState === 'state_b' || senderState === 'state_c'
      ? activeSessionCode
      : null,
    participantId,
  )

  // ─── バッテリー API ───────────────────────────────────────────────────────
  useEffect(() => {
    const nav = navigator as any
    if (!nav.getBattery) return
    let bm: BatteryManager | null = null
    const update = () => {
      if (bm) setBattery({ level: bm.level, charging: bm.charging })
    }
    nav.getBattery().then((b: BatteryManager) => {
      bm = b
      update()
      b.addEventListener('levelchange', update)
      b.addEventListener('chargingchange', update)
    })
    return () => {
      if (bm) {
        bm.removeEventListener('levelchange', update)
        bm.removeEventListener('chargingchange', update)
      }
    }
  }, [])

  // ─── 縦横向き検知（state_c で横向き要求） ────────────────────────────────
  useEffect(() => {
    const update = () => setIsPortrait(window.innerHeight > window.innerWidth)
    window.addEventListener('resize', update)
    window.addEventListener('orientationchange', update)
    return () => {
      window.removeEventListener('resize', update)
      window.removeEventListener('orientationchange', update)
    }
  }, [])

  // ─── RTT 計測 ─────────────────────────────────────────────────────────────
  const startRttPolling = useCallback((pc: RTCPeerConnection) => {
    rttTimerRef.current = setInterval(async () => {
      try {
        const stats = await pc.getStats()
        stats.forEach((report) => {
          if (report.type === 'candidate-pair' && report.state === 'succeeded' && report.currentRoundTripTime != null) {
            setRttMs(Math.round(report.currentRoundTripTime * 1000))
          }
        })
      } catch { /* ignore */ }
    }, 3000)
  }, [])

  const stopRttPolling = useCallback(() => {
    if (rttTimerRef.current) {
      clearInterval(rttTimerRef.current)
      rttTimerRef.current = null
    }
    setRttMs(null)
  }, [])

  // ─── 自動再接続 ───────────────────────────────────────────────────────────
  const scheduleReconnect = useCallback((code: string, pid: number) => {
    const count = reconnectCountRef.current + 1
    if (count > MAX_RECONNECT) {
      setSenderState('error')
      setErrorMsg(t('camera_sender.reconnect_failed'))
      return
    }
    reconnectCountRef.current = count
    setReconnectCount(count)
    setSenderState('connecting')
    reconnectTimerRef.current = setTimeout(() => {
      connectWs(code, pid) // eslint-disable-line
    }, RECONNECT_DELAY_MS)
  }, [t]) // connectWs is defined below and used via closure

  // ─── WebSocket 接続 ───────────────────────────────────────────────────────
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const connectWs = useCallback((code: string, pid: number) => {
    if (wsRef.current) {
      wsRef.current.onclose = null
      wsRef.current.onerror = null
      wsRef.current.close()
      wsRef.current = null
    }

    // Electron(file:) → ws://localhost:8765
    // LAN直接(http:)  → ws://192.168.x.x:8765
    // Cloudflareトンネル(https:) → wss://xxxx.trycloudflare.com (ポートなし)
    const isElectron = window.location.protocol === 'file:'
    const isHttps = window.location.protocol === 'https:'
    const wsProto = isHttps ? 'wss' : 'ws'
    const wsHost = isElectron ? 'localhost:8765' : isHttps ? window.location.host : `${window.location.hostname}:8765`
    const wsToken = isHttps ? (sessionStorage.getItem('shuttlescope_token') ?? '') : ''
    const wsUrl = `${wsProto}://${wsHost}/ws/camera/${code}?participant_id=${pid}${wsToken ? `&token=${wsToken}` : ''}`
    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onopen = () => {
      reconnectCountRef.current = 0
      setReconnectCount(0)
      ws.send(JSON.stringify({
        type: 'device_hello',
        participant_id: pid,
        device_name: savedDeviceNameRef.current || `${getDeviceType()}-camera`,
        device_type: getDeviceType(),
      }))
      setSenderState('state_a')
    }

    ws.onmessage = async (event) => {
      try {
        const msg = JSON.parse(event.data)
        if (msg.type === 'camera_request') {
          setSenderState('state_b')
        } else if (msg.type === 'camera_deactivate') {
          // オペレーターから待機に戻す指示
          localStreamRef.current?.getTracks().forEach((t) => t.stop())
          localStreamRef.current = null
          pcRef.current?.close()
          pcRef.current = null
          if (previewRef.current) previewRef.current.srcObject = null
          setSenderState('state_a')
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
      const st = senderStateRef.current
      if (st === 'state_c' || st === 'state_a' || st === 'state_b') {
        scheduleReconnect(code, pid)
      }
    }

    ws.onerror = () => {
      // onclose も発火するので状態変更はそちらに委ねる
    }
  }, [scheduleReconnect])

  // ─── セッション参加 ───────────────────────────────────────────────────────
  const joinSession = useCallback(async (code: string, password: string, deviceName: string) => {
    setSenderState('connecting')
    setErrorMsg('')
    const resolvedName = deviceName || localStorage.getItem(DEVICE_NAME_KEY) || getDeviceTypeLabel()
    // 使用した名前をlocalStorageに保存
    localStorage.setItem(DEVICE_NAME_KEY, resolvedName)
    savedCodeRef.current = code
    savedPasswordRef.current = password
    savedDeviceNameRef.current = resolvedName
    try {
      const res = await apiPost<{
        success: boolean
        data: { participant_id: number; session_code: string; role: string; connection_role: string }
      }>(`/sessions/${code}/join`, {
        role: 'viewer',
        device_name: resolvedName,
        device_type: getDeviceType(),
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
      if (status === 401) {
        setErrorMsg(t('camera_sender.join_error_invalid'))
      } else if (status === 404) {
        setErrorMsg('セッションが見つかりません。コードを確認してください。')
      } else {
        setErrorMsg(t('camera_sender.join_error_network'))
      }
      setSenderState('join')
    }
  }, [t, connectWs])

  // URL からセッションコードが渡された場合は直接参加試行
  useEffect(() => {
    if (paramCode && senderState === 'connecting') {
      if (pwdParam) {
        // ?pwd= パラメータがあれば自動入力してパスワードフォームをスキップ（保存済み端末名を使用）
        joinSession(paramCode, pwdParam, localStorage.getItem(DEVICE_NAME_KEY) || getDeviceTypeLabel())
      } else {
        // 旧 QR コード（パスワードなし URL）→ フォームに誘導
        setErrorMsg('QRコードを再生成するか、下のフォームにパスワードを入力してください。')
        setSenderState('join')
      }
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ─── カメラ起動 & WebRTC offer ────────────────────────────────────────────
  const startCamera = useCallback(async () => {
    // iOS Safari は HTTP（非セキュアコンテキスト）では mediaDevices が undefined になる
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setErrorMsg('カメラにアクセスできません。HTTPSまたはlocalhostで開いてください（iOSはHTTPではカメラ使用不可）。')
      return
    }
    try {
      // ICE サーバー設定を取得（TURN が有効な場合はリレー経由）
      let iceServers: RTCIceServer[] = [{ urls: 'stun:stun.l.google.com:19302' }]
      try {
        const iceCfg = await apiGet<{ success: boolean; data: { ice_servers: RTCIceServer[] } }>('/webrtc/ice-config')
        if (iceCfg.success && iceCfg.data.ice_servers.length > 0) {
          iceServers = iceCfg.data.ice_servers
        }
      } catch { /* バックエンド未起動時はデフォルト STUN を使用 */ }

      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      })
      localStreamRef.current = stream
      if (previewRef.current) {
        previewRef.current.srcObject = stream
      }

      const pc = new RTCPeerConnection({ iceServers })
      pcRef.current = pc
      startRttPolling(pc)

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
  }, [participantId, startRttPolling])

  // ─── 配信停止 ─────────────────────────────────────────────────────────────
  const stopCamera = useCallback(() => {
    stopRttPolling()
    localStreamRef.current?.getTracks().forEach((t) => t.stop())
    localStreamRef.current = null
    pcRef.current?.close()
    pcRef.current = null
    wsRef.current?.send(JSON.stringify({
      type: 'camera_stop',
      participant_id: participantId,
    }))
    setSenderState('state_a')
  }, [participantId, stopRttPolling])

  // ─── Page Visibility API（iOS バックグラウンド復帰対応） ────────────────────
  useEffect(() => {
    const onVisibilityChange = () => {
      if (document.visibilityState !== 'visible') return
      // フォアグラウンド復帰時に WS が切断されていたら再接続を試みる
      const st = senderStateRef.current
      if (
        (st === 'state_a' || st === 'state_b' || st === 'state_c') &&
        wsRef.current === null &&
        savedCodeRef.current &&
        savedPidRef.current !== null
      ) {
        reconnectCountRef.current = 0
        setReconnectCount(0)
        setSenderState('connecting')
        connectWs(savedCodeRef.current, savedPidRef.current)
      }
    }
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => document.removeEventListener('visibilitychange', onVisibilityChange)
  }, [connectWs])

  // アンマウント時クリーンアップ
  useEffect(() => {
    return () => {
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
      stopRttPolling()
      localStreamRef.current?.getTracks().forEach((t) => t.stop())
      pcRef.current?.close()
      wsRef.current?.onclose && (wsRef.current.onclose = null)
      wsRef.current?.close()
    }
  }, [stopRttPolling])

  // ─── ステータスバー（全状態共通） ─────────────────────────────────────────
  const StatusBar = () => (
    <div className="flex items-center justify-between w-full max-w-sm mb-3 px-1">
      {activeSessionCode && (
        <SessionBadge
          sessionCode={activeSessionCode}
          role={savedDeviceNameRef.current || getDeviceTypeLabel()}
        />
      )}
      <div className="flex items-center gap-2 ml-auto">
        {battery && <BatteryIndicator level={battery.level} charging={battery.charging} />}
        {rttMs !== null && <NetworkQualityIndicator rttMs={rttMs} />}
      </div>
    </div>
  )

  // ─── レンダリング ──────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-gray-900 text-white flex flex-col items-center justify-center p-4">
      {/* ロゴ */}
      <div className="mb-4 text-center">
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
          <p className="text-gray-300 text-sm">
            {reconnectCount > 0
              ? `${t('camera_sender.reconnecting')} (${reconnectCount}/${MAX_RECONNECT}${t('camera_sender.reconnect_attempt')})`
              : t('camera_sender.join_connecting')}
          </p>
        </div>
      )}

      {/* ─── State A: 待機 ──────────────── */}
      {senderState === 'state_a' && (
        <div className="w-full max-w-sm flex flex-col items-center">
          <StatusBar />
          <div className="w-full bg-gray-800 rounded-xl p-8 shadow-2xl text-center">
            <div className="w-16 h-16 rounded-full bg-blue-900/50 flex items-center justify-center mx-auto mb-4">
              <Camera size={28} className="text-blue-400" />
            </div>
            <p className="text-lg font-semibold mb-2">{t('camera_sender.state_a_title')}</p>
            <p className="text-gray-400 text-sm leading-relaxed">{t('camera_sender.state_a_hint')}</p>
            <div className="mt-4 flex items-center justify-center gap-1.5 text-green-400 text-xs">
              <CheckCircle2 size={14} />
              {t('camera_sender.status_connected')}
            </div>
            {/* 端末名表示・編集 */}
            <div className="mt-4 border-t border-gray-700 pt-4">
              {editingName ? (
                <div className="flex items-center gap-2">
                  <input
                    autoFocus
                    value={nameInput}
                    onChange={(e) => setNameInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        const n = nameInput.trim() || getDeviceTypeLabel()
                        localStorage.setItem(DEVICE_NAME_KEY, n)
                        savedDeviceNameRef.current = n
                        setEditingName(false)
                      }
                      if (e.key === 'Escape') setEditingName(false)
                    }}
                    className="flex-1 bg-gray-700 rounded px-2 py-1 text-sm text-white text-center focus:outline-none focus:ring-1 focus:ring-blue-500"
                    placeholder={getDeviceTypeLabel()}
                    maxLength={32}
                  />
                  <button
                    onClick={() => {
                      const n = nameInput.trim() || getDeviceTypeLabel()
                      localStorage.setItem(DEVICE_NAME_KEY, n)
                      savedDeviceNameRef.current = n
                      setEditingName(false)
                    }}
                    className="p-1 text-green-400 hover:text-green-300"
                  >
                    <Check size={16} />
                  </button>
                </div>
              ) : (
                <div className="flex items-center justify-center gap-2">
                  <span className="text-xs text-gray-400">
                    端末名: <span className="text-gray-200 font-medium">{savedDeviceNameRef.current || getDeviceTypeLabel()}</span>
                  </span>
                  <button
                    onClick={() => { setNameInput(savedDeviceNameRef.current || getDeviceTypeLabel()); setEditingName(true) }}
                    className="p-1 text-gray-500 hover:text-gray-300 rounded"
                    title="端末名を編集"
                  >
                    <Pencil size={12} />
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ─── State B: 確認 ──────────────── */}
      {senderState === 'state_b' && (
        <div className="w-full max-w-sm flex flex-col items-center">
          <StatusBar />
          <div className="w-full bg-gray-800 rounded-xl p-6 shadow-2xl border border-amber-500/40">
            <div className="w-16 h-16 rounded-full bg-amber-900/50 flex items-center justify-center mx-auto mb-4">
              <Camera size={28} className="text-amber-400" />
            </div>
            <p className="text-center text-lg font-semibold mb-2">{t('camera_sender.state_b_title')}</p>
            <p className="text-center text-xs text-gray-400 mb-5">
              コートを映せる場所に端末を固定してから起動してください。
            </p>
            {errorMsg && (
              <div className="flex items-start gap-1.5 text-red-400 text-xs mb-3 bg-red-900/30 rounded-lg p-2">
                <XCircle size={14} className="shrink-0 mt-0.5" />
                {errorMsg}
              </div>
            )}
            <div className="space-y-2">
              <button
                onClick={startCamera}
                className="w-full py-3 rounded-xl bg-red-600 hover:bg-red-500 text-white font-semibold flex items-center justify-center gap-2"
              >
                <Camera size={18} />
                {t('camera_sender.state_b_start')}
              </button>
              <button
                onClick={() => { setSenderState('state_a'); setErrorMsg('') }}
                className="w-full py-2.5 rounded-xl bg-gray-700 hover:bg-gray-600 text-gray-300 text-sm"
              >
                {t('camera_sender.state_b_cancel')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ─── State C: 送信中（縦向き時はCSS回転で強制横表示） ── */}
      {senderState === 'state_c' && (
        <div
          className="flex flex-col items-center"
          style={isPortrait ? {
            position: 'fixed',
            width: '100vh',
            height: '100vw',
            top: 'calc(50vh - 50vw)',
            left: 'calc(50vw - 50vh)',
            transform: 'rotate(90deg)',
            transformOrigin: 'center center',
            overflowY: 'auto',
          } : { width: '100%', maxWidth: '384px' }}
        >
          <StatusBar />
          {/* カメラプレビュー */}
          <div className="relative w-full mb-4 rounded-xl overflow-hidden bg-black aspect-video">
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
            <p className="text-sm text-gray-300 mb-1">{errorMsg || t('camera_sender.join_error_network')}</p>
            <p className="text-xs text-gray-500 mb-4">
              Wi-Fi に接続されているか確認してから再試行してください。
            </p>
            <div className="flex gap-2 justify-center">
              <button
                onClick={() => {
                  reconnectCountRef.current = 0
                  setReconnectCount(0)
                  const code = savedCodeRef.current
                  const pid = savedPidRef.current
                  if (code && pid) {
                    connectWs(code, pid)
                  } else {
                    setSenderState('join')
                  }
                }}
                className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-sm"
              >
                もう一度試す
              </button>
              <button
                onClick={() => { setSenderState('join'); setErrorMsg('') }}
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
