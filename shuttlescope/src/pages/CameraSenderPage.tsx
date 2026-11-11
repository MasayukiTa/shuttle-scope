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
 *   - 非技術ユーザ向け丁寧な状態テキスト
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams, useLocation, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { apiPost, getParticipantIceConfig } from '@/api/client'
import { useDeviceHeartbeat } from '@/hooks/useDeviceHeartbeat'
import { useServerSideRecording } from '@/hooks/session/useServerSideRecording'
import { RecordingProblemNotice } from '@/components/camera/RecordingProblemNotice'
import { errorStatus, errorMessage } from '@/utils/errors'
import { participantWsUrl } from '@/utils/cameraWs'
import { getDeviceUid } from '@/utils/deviceUid'
import { getParticipantRejoinToken, setParticipantRejoinToken } from '@/utils/participantRejoinToken'
import { MIcon } from '@/components/common/MIcon'
import { watchPeerConnection, addCandidate, flushCandidates } from './peerConnection'

type SenderState = 'join' | 'connecting' | 'waiting_approval' | 'state_a' | 'state_b' | 'state_c' | 'error'

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

// 入場券取得の 403 本文から機械可読なエラーコードを取り出す。
// サーバー (backend/routers/sessions.py issue_camera_ws_ticket) は未承認・拒否を
// detail={code, message} で返す。文言に依存せずコードで待機/拒否/再参加を分ける。
function approvalErrorCode(e: unknown): string | null {
  const body = errorMessage(e)
  if (!body) return null
  try {
    const parsed = JSON.parse(body) as { detail?: unknown }
    const detail = parsed?.detail
    if (detail && typeof detail === 'object') {
      const code = (detail as { code?: unknown }).code
      if (typeof code === 'string') return code
    }
  } catch { /* detail が文字列などコードを含まない形式 */ }
  return null
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
  const iconName = pct > 60 ? 'battery_full' : pct > 25 ? 'battery_5_bar' : 'battery_2_bar'
  const color = pct > 60 ? 'text-[var(--ss-good)]' : pct > 25 ? 'text-[var(--ss-warn)]' : 'text-[var(--ss-bad)]'
  return (
    <span className={`flex items-center gap-0.5 text-[10px] ${color}`}>
      <MIcon name={iconName} size={12} />
      <span className="ss-num">{pct}%</span>{charging ? <MIcon name="bolt" size={10} className="ml-0.5" /> : null}
    </span>
  )
}

// ─── ネットワーク品質表示 ────────────────────────────────────────────────────

function NetworkQualityIndicator({ rttMs }: { rttMs: number | null }) {
  const { t } = useTranslation()
  if (rttMs === null) return null
  const good = rttMs < 80
  const iconName = good ? 'wifi' : 'signal_wifi_0_bar'
  const color = good ? 'text-[var(--ss-good)]' : 'text-[var(--ss-warn)]'
  return (
    <span className={`flex items-center gap-0.5 text-[10px] ${color}`}>
      <MIcon name={iconName} size={12} />
      {t('camera_sender.network_quality')} <span className="ss-num">{rttMs}ms</span>
    </span>
  )
}

// ─── セッション情報バッジ ────────────────────────────────────────────────────

function SessionBadge({ sessionCode, deviceName }: { sessionCode: string; deviceName: string }) {
  const { t } = useTranslation()
  return (
    <div className="flex items-center gap-2 text-[10px] text-[var(--ss-t3)] mb-1">
      <span>{t('camera_sender.session_label')}: <span className="font-mono ss-num text-[var(--ss-t2)]">{sessionCode}</span></span>
      <span>|</span>
      <span>{t('camera_sender.role_display')}: <span className="text-[var(--ss-brand)]">{deviceName}</span></span>
    </div>
  )
}

// ─── メインコンポーネント ────────────────────────────────────────────────────

const MAX_RECONNECT = 10
const RECONNECT_DELAY_MS = 5_000
const APPROVAL_RECHECK_DELAY_MS = 3_000
const DEVICE_NAME_KEY = 'ss_device_name'

export function CameraSenderPage() {
  const { sessionCode: paramCode } = useParams<{ sessionCode: string }>()
  const { search, pathname } = useLocation()
  const navigate = useNavigate()
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
  // error 画面で Wi-Fi 確認の案内を出すかどうか。通信エラー起因の失敗のときだけ true。
  // 承認待ち・拒否・再参加要求は通信の問題ではないので Wi-Fi 案内を出さない。
  const [showWifiHint, setShowWifiHint] = useState(false)
  // 端末名インライン編集用
  const [editingName, setEditingName] = useState(false)
  const [nameInput, setNameInput] = useState('')
  const [isPortrait, setIsPortrait] = useState(() => window.innerHeight > window.innerWidth)
  const [participantId, setParticipantId] = useState<number | null>(null)
  const [participantToken, setParticipantToken] = useState('')
  const [activeSessionCode, setActiveSessionCode] = useState<string>(paramCode ?? '')
  const [reconnectCount, setReconnectCount] = useState(0)
  // R-1: サーバ自動録画用 match_id (session join のレスポンスから取得)
  const [recordingMatchId, setRecordingMatchId] = useState<number | null>(null)
  const serverRecorder = useServerSideRecording({
    matchId: recordingMatchId,
    sessionCode: activeSessionCode,
    participantId,
    participantToken,
  })
  const [battery, setBattery] = useState<{ level: number; charging: boolean } | null>(null)
  const [rttMs, setRttMs] = useState<number | null>(null)
  const [startingCamera, setStartingCamera] = useState(false)
  // 接続に時間がかかっているときの案内 (5 秒超)。paramCode 自動参加で connecting が長引く症状 (T011) 向け。
  const [slowConnect, setSlowConnect] = useState(false)

  const wsRef = useRef<WebSocket | null>(null)
  const pcRef = useRef<RTCPeerConnection | null>(null)
  const candidatesRef = useRef<RTCIceCandidateInit[]>([])
  const localStreamRef = useRef<MediaStream | null>(null)
  const previewRef = useRef<HTMLVideoElement>(null)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const approvalRecheckTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const rttTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  // 再接続判定用 ref（stale closure 回避）
  const senderStateRef = useRef<SenderState>(senderState)
  const reconnectCountRef = useRef(0)
  const savedCodeRef = useRef(paramCode ?? '')
  const savedPidRef = useRef<number | null>(null)
  const savedPasswordRef = useRef('')
  const savedDeviceNameRef = useRef('')
  // join で一度だけ返る参加者トークン。WS 入場券の引き換えに使う。
  // sessionStorage には置かない (この端末のこのタブの寿命だけで十分)。
  const savedTokenRef = useRef('')
  // 入場券取得の await 中にアンマウントされたら WS を開かないための番人
  const disposedRef = useRef(false)

  useEffect(() => { senderStateRef.current = senderState }, [senderState])

  // ─── 接続遅延の案内 (T011) ───────────────────────────────────────────────
  // connecting のまま 5 秒を超えたら『時間がかかっています』を出す。接続成功・
  // 失敗・他状態への遷移でタイマーを畳み、案内も消す (通信エラーの案内は error 画面側)。
  useEffect(() => {
    if (senderState !== 'connecting') {
      setSlowConnect(false)
      return
    }
    setSlowConnect(false)
    const timer = setTimeout(() => setSlowConnect(true), 5_000)
    return () => clearTimeout(timer)
  }, [senderState])

  // server 側で参加者が削除されたとき (heartbeat が 404/410/401) の処理。
  // 最新の state / ref を使うため ref 経由で呼ぶ (フックへ渡す関数の同一性を保つ)。
  const onRemovedRef = useRef<() => void>(() => {})
  const handleRemoved = useCallback(() => onRemovedRef.current(), [])

  // ─── ハートビート ─────────────────────────────────────────────────────────
  useDeviceHeartbeat(
    senderState === 'state_a' || senderState === 'state_b' || senderState === 'state_c'
      ? activeSessionCode
      : null,
    participantId,
    handleRemoved,
    // JWT を持たない参加端末はこのトークンで認証される
    savedTokenRef.current || undefined,
  )

  // ─── バッテリー API ───────────────────────────────────────────────────────
  useEffect(() => {
    const nav = navigator as Navigator & { getBattery?: () => Promise<BatteryManager> }
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
      // 再接続が尽きた = 通信の問題。ここでだけ Wi-Fi 確認の案内を出す。
      setShowWifiHint(true)
      return
    }
    reconnectCountRef.current = count
    setReconnectCount(count)
    setSenderState('connecting')
    reconnectTimerRef.current = setTimeout(() => {
      void connectWs(code, pid)
    }, RECONNECT_DELAY_MS)
    // connectWs is defined below and used via closure (mutually recursive callbacks)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [t])

  // ─── 承認待ちの再確認 ─────────────────────────────────────────────────────
  // operator がまだ承認していない端末は 403(device_not_approved) で弾かれる。
  // これは通信エラーではないので reconnectCount を消費せず、一定間隔で入場券を
  // 取り直す。承認された瞬間に connectWs が成功し、通常の接続フローへ進む。
  const scheduleApprovalRecheck = useCallback((code: string, pid: number) => {
    if (approvalRecheckTimerRef.current) {
      clearTimeout(approvalRecheckTimerRef.current)
    }
    approvalRecheckTimerRef.current = setTimeout(() => {
      void connectWs(code, pid)
    }, APPROVAL_RECHECK_DELAY_MS)
    // connectWs is defined below and used via closure (mutually recursive callbacks)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ─── WebSocket 接続 ───────────────────────────────────────────────────────
   
  const connectWs = useCallback(async (code: string, pid: number) => {
    if (wsRef.current) {
      wsRef.current.onclose = null
      wsRef.current.onerror = null
      wsRef.current.close()
      wsRef.current = null
    }

    // join で得た参加者トークンを 30 秒使い捨ての入場券に引き換える。
    // 失敗したら通常の切断と同じ扱いで再接続へ回す。
    let wsUrl: string
    try {
      wsUrl = await participantWsUrl(code, 'device', pid, savedTokenRef.current)
    } catch (e) {
      // #665 / 承認フロー: 入場券取得の失敗を握りつぶして一律再接続せず、原因で分ける。
      //   403 + code=device_not_approved → まだ承認されていない。エラーにせず『承認待ち』
      //     画面を出し、3 秒ごとに入場券を取り直す。operator が承認した瞬間に接続へ進む。
      //   403 + code=device_rejected    → 拒否。再試行しても直らないので専用の案内。
      //   その他の 401/403・参加トークン欠落 → 再参加案内 (rejoin_required)。
      //   404/410 → セッション消滅。
      //   5xx/タイムアウト/ネットワーク断のみ → 有限回の自動再接続。
      const status = errorStatus(e)
      const approvalCode = approvalErrorCode(e)
      if (status === 403 && approvalCode === 'device_not_approved') {
        // 承認待ちは通信エラーではない。待機画面を出し Wi-Fi 案内は出さない。
        // 確認するたびに時刻つきで『まだ承認されていません』を言い直す (手動/自動とも)。
        setShowWifiHint(false)
        setErrorMsg('')
        setSenderState('waiting_approval')
        scheduleApprovalRecheck(code, pid)
        return
      }
      if (status === 403 && approvalCode === 'device_rejected') {
        setShowWifiHint(false)
        setSenderState('error')
        setErrorMsg(t('camera_sender.device_rejected'))
      } else if (status === 401 || status === 403 || !savedTokenRef.current) {
        setShowWifiHint(false)
        setSenderState('error')
        setErrorMsg(t('camera_sender.rejoin_required'))
      } else if (status === 404 || status === 410) {
        setShowWifiHint(false)
        setSenderState('error')
        setErrorMsg(t('camera_sender.session_gone'))
      } else {
        scheduleReconnect(code, pid)
      }
      return
    }
    if (disposedRef.current) return

    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onopen = () => {
      reconnectCountRef.current = 0
      setReconnectCount(0)
      // 接続できた = 承認済みで通信も回復。承認待ち再確認と Wi-Fi 案内を止める。
      if (approvalRecheckTimerRef.current) {
        clearTimeout(approvalRecheckTimerRef.current)
        approvalRecheckTimerRef.current = null
      }
      setShowWifiHint(false)
      // 再接続時、サーバ側は **新しい stream_id を採番して古い対応を捨てる**
      // (ws/camera.py の _new_stream_id)。旧実装はここで device_hello を
      // 送って state_a に戻すだけで、**古い RTCPeerConnection を閉じも
      // 再 offer もしなかった**。結果、カメラは点いたまま映像が流れず、
      // 画面は「待機中」と表示し続ける — 失敗したことが誰にも分からない。
      // 古い接続をここで畳み、operator からの camera_request で作り直す。
      if (pcRef.current) {
        try {
          pcRef.current.close()
        } catch { /* 既に閉じている場合がある */ }
        pcRef.current = null
      }
      ws.send(JSON.stringify({
        type: 'device_hello',
        participant_id: pid,
        device_name: savedDeviceNameRef.current || `${getDeviceType()}-camera`,
        device_type: getDeviceType(),
      }))
      setSenderState('state_a')
    }

    ws.onmessage = async (event) => {
      let msg
      try { msg = JSON.parse(event.data) } catch { console.warn('Invalid signaling message'); return }
      try {
        if (msg.type === 'camera_request') {
          setSenderState('state_b')
        } else if (msg.type === 'camera_deactivate') {
          // オペレーターから待機に戻す指示
          void serverRecorder.stop()
          localStreamRef.current?.getTracks().forEach((t) => t.stop())
          localStreamRef.current = null
          pcRef.current?.close()
          pcRef.current = null
          setStartingCamera(false)
          if (previewRef.current) previewRef.current.srcObject = null
          setSenderState('state_a')
        } else if (msg.type === 'webrtc_answer' && pcRef.current) {
          const pc = pcRef.current
          await pc.setRemoteDescription({ type: 'answer', sdp: msg.sdp })
          if (pcRef.current === pc) await flushCandidates(pc, candidatesRef.current)
        } else if (msg.type === 'ice_candidate' && pcRef.current) {
          await addCandidate(pcRef.current, candidatesRef.current, {
            candidate: msg.candidate,
            sdpMid: msg.sdp_mid,
            sdpMLineIndex: msg.sdp_m_line_index,
          })
        }
      } catch (error) {
        console.warn('WebRTC signaling failed', error)
        setStartingCamera(false)
        localStreamRef.current?.getTracks().forEach((track) => track.stop())
        localStreamRef.current = null
        stopRttPolling()
        void serverRecorder.stop()
        pcRef.current?.close()
        pcRef.current = null
        candidatesRef.current = []
        setErrorMsg(t('camera_sender.connect_error'))
        setSenderState('error')
      }
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
    // serverRecorder は安定参照 (custom hook の戻り値) なので deps 不要
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scheduleReconnect, t])

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
      const deviceUid = getDeviceUid()
      const previousParticipantToken = getParticipantRejoinToken(code, deviceUid)
      const res = await apiPost<{
        success: boolean
        data: {
          participant_id: number; session_code: string; role: string;
          connection_role: string; match_id?: number | null
          participant_token?: string
        }
      }>(`/sessions/${code}/join`, {
        role: 'viewer',
        device_name: resolvedName,
        device_type: getDeviceType(),
        device_uid: deviceUid,
        participant_token: previousParticipantToken || undefined,
        session_password: password || undefined,
      })
      if (!res.success) throw new Error('join failed')
      const pid = res.data.participant_id
      setParticipantId(pid)
      savedPidRef.current = pid
      // WS 入場券の引き換えに使う。平文はこの応答でしか返らない。
      savedTokenRef.current = res.data.participant_token ?? ''
      if (savedTokenRef.current) {
        setParticipantRejoinToken(code, deviceUid, savedTokenRef.current)
      }
      setParticipantToken(savedTokenRef.current)
      setActiveSessionCode(code)
      // R-1: サーバ自動録画用 match_id を保存
      if (res.data.match_id != null) {
        setRecordingMatchId(res.data.match_id)
      }
      reconnectCountRef.current = 0
      void connectWs(code, pid)
    } catch (err: unknown) {
      const status = errorStatus(err)
      if (status === 401) {
        setErrorMsg(t('camera_sender.join_error_invalid'))
      } else if (status === 404) {
        setErrorMsg('セッションが見つかりません。コードを確認してください。')
      } else if (status === 429) {
        // 承認待ちが上限、または参加要求が多すぎる (W63)。少し待てば回復する。
        setErrorMsg(t('lan_session.join_pending_cap'))
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
        // 参加に使ったら URL からパスワードを消す（履歴・アドレスバー・共有に残さない）
        navigate({ pathname, search: '' }, { replace: true })
        joinSession(paramCode, pwdParam, localStorage.getItem(DEVICE_NAME_KEY) || getDeviceTypeLabel())
      } else {
        // 旧 QR コード（パスワードなし URL）→ フォームに誘導
        setErrorMsg(t('lan_session.join_password_required'))
        setSenderState('join')
      }
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ─── カメラ起動 & WebRTC offer ────────────────────────────────────────────
  const startCamera = useCallback(async () => {
    // iOS Safari は HTTP（非セキュアコンテキスト）では mediaDevices が undefined になる
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setErrorMsg(t('camera_sender.camera_error_insecure'))
      return
    }
    setStartingCamera(true)
    // カメラ取得・WebRTC 確立を段階ごとに分けて扱う。getUserMedia の失敗は端末の
    // カメラ権限/使用状況の問題、それ以降 (PeerConnection / SDP / signaling) の失敗は
    // 通信接続の問題として、利用者向けに別々の案内を出す。両者を同じ catch で
    // 「カメラ権限を許可してください」と扱うと、権限を見直しても直らない誤案内になる。
    let stream: MediaStream
    try {
      // 前回の stream を止めてから取り直す。止めずに上書きすると
      // 古いトラックが生き続け、端末のカメラ表示 (LED) が点いたままになり、
      // 電池とメモリを食う。
      if (localStreamRef.current) {
        localStreamRef.current.getTracks().forEach((t) => {
          try {
            t.stop()
          } catch { /* 既に停止している場合がある */ }
        })
      }
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      })
    } catch (err) {
      // getUserMedia の DOMException だけをカメラ取得エラーとして種別ごとに案内する。
      const name = (err as { name?: string } | null)?.name
      if (name === 'NotAllowedError' || name === 'SecurityError') {
        setErrorMsg(t('camera_sender.camera_error_permission'))
      } else if (name === 'NotFoundError' || name === 'OverconstrainedError') {
        setErrorMsg(t('camera_sender.camera_error_notfound'))
      } else if (name === 'NotReadableError' || name === 'AbortError') {
        setErrorMsg(t('camera_sender.camera_error_inuse'))
      } else {
        setErrorMsg(t('camera_sender.camera_error_generic'))
      }
      setStartingCamera(false)
      return
    }

    try {
      localStreamRef.current = stream
      if (previewRef.current) {
        previewRef.current.srcObject = stream
      }

      // R-1: サーバ自動録画 (match_id 取得済 + 自動録画 ON 時)
      if (recordingMatchId != null) {
        void serverRecorder.start(stream).catch(() => { /* noop */ })
      }

      // ICE サーバー設定を取得（TURN が有効な場合はリレー経由）
      let iceServers: RTCIceServer[] = [{ urls: 'stun:stun.l.google.com:19302' }]
      try {
        if (participantId == null || !savedTokenRef.current || !activeSessionCode) {
          throw new Error('participant credential unavailable')
        }
        const iceCfg = await getParticipantIceConfig(
          activeSessionCode,
          participantId,
          savedTokenRef.current,
        )
        if (iceCfg.success && iceCfg.data.ice_servers.length > 0) {
          iceServers = iceCfg.data.ice_servers
        }
      } catch { /* バックエンド未起動時はデフォルト STUN を使用 */ }

      // 再開のたびに前の PeerConnection とトラックを閉じずに上書きしていた。
      // カメラの LED が点いたまま、メモリと電池を食い続ける。
      if (pcRef.current) {
        try {
          pcRef.current.close()
        } catch { /* 既に閉じている場合がある */ }
      }
      const pc = new RTCPeerConnection({ iceServers })
      pcRef.current = pc
      candidatesRef.current = []
      watchPeerConnection(pc, () => pcRef.current === pc,
        () => { setStartingCamera(false); setSenderState('state_c') },
        () => {
          pc.close()
          pcRef.current = null
          localStreamRef.current?.getTracks().forEach((track) => track.stop())
          localStreamRef.current = null
          stopRttPolling()
          void serverRecorder.stop()
          setStartingCamera(false)
          setErrorMsg(t('camera_sender.connect_error'))
          setSenderState('error')
        })
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

    } catch {
      // ここに来るのはカメラ取得後の WebRTC/signaling 失敗なので、カメラ権限ではなく
      // 接続の問題として案内する。取得済みの stream は止めてカメラを解放する。
      try {
        stream.getTracks().forEach((t) => t.stop())
      } catch { /* 既に停止している場合がある */ }
      localStreamRef.current = null
      pcRef.current?.close()
      pcRef.current = null
      setErrorMsg(t('camera_sender.connect_error'))
      setSenderState('error')
      setStartingCamera(false)
    }
    // recordingMatchId / serverRecorder は read-only スナップショットとして使い、
    // 再カメラ起動時に最新値で動けばよい (callback 再生成は不要)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [participantId, startRttPolling, t])

  // ─── 配信停止 ─────────────────────────────────────────────────────────────
  const stopCamera = useCallback(() => {
    stopRttPolling()
    // R-1: サーバ録画があれば finalize して artifact を確定させる
    void serverRecorder.stop()
    localStreamRef.current?.getTracks().forEach((t) => t.stop())
    localStreamRef.current = null
    pcRef.current?.close()
    pcRef.current = null
    wsRef.current?.send(JSON.stringify({
      type: 'camera_stop',
      participant_id: participantId,
    }))
    setSenderState('state_a')
  }, [participantId, stopRttPolling, serverRecorder])

  // オペレーターに外された (server 側で削除された) とき、接続中の表示を残さない。
  // 録画の確定・カメラ停止・PeerConnection / WS の後始末をして、案内つきのエラー画面へ移る。
  useEffect(() => {
    onRemovedRef.current = () => {
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
      if (approvalRecheckTimerRef.current) clearTimeout(approvalRecheckTimerRef.current)
      stopRttPolling()
      void serverRecorder.stop()
      localStreamRef.current?.getTracks().forEach((tr) => tr.stop())
      localStreamRef.current = null
      pcRef.current?.close()
      pcRef.current = null
      // onclose を外してから閉じる (自動再接続させない)
      if (wsRef.current?.onclose) wsRef.current.onclose = null
      wsRef.current?.close()
      wsRef.current = null
      savedPidRef.current = null
      savedTokenRef.current = ''
      setParticipantId(null)
      setParticipantToken('')
      setActiveSessionCode('')
      setErrorMsg(t('camera_sender.removed_by_operator'))
      setSenderState('error')
    }
  }, [stopRttPolling, serverRecorder, t])

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
        void connectWs(savedCodeRef.current, savedPidRef.current)
      }
    }
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => document.removeEventListener('visibilitychange', onVisibilityChange)
  }, [connectWs])

  // アンマウント時クリーンアップ
  useEffect(() => {
    // StrictMode は setup → cleanup → setup と二度走る。ここで false に
    // 戻さないと、二度目以降の接続が入場券取得後に必ず中止される。
    disposedRef.current = false
    return () => {
      disposedRef.current = true
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
      if (approvalRecheckTimerRef.current) clearTimeout(approvalRecheckTimerRef.current)
      stopRttPolling()
      localStreamRef.current?.getTracks().forEach((t) => t.stop())
      pcRef.current?.close()
      if (wsRef.current?.onclose) wsRef.current.onclose = null
      wsRef.current?.close()
    }
  }, [stopRttPolling])

  // ─── 端末名の保存 ─────────────────────────────────────────────────────────
  // 名前を localStorage と ref に保存し、WS が開いていればサーバへ device_rename を
  // 送る。サーバは参加者行の名前を更新し、device_list_update で operator に配る。
  // connectWs / PeerConnection には触れない (この 1 本の送信だけ)。
  const saveDeviceName = useCallback((raw: string) => {
    const n = raw.trim() || getDeviceTypeLabel()
    localStorage.setItem(DEVICE_NAME_KEY, n)
    savedDeviceNameRef.current = n
    const pid = participantId ?? savedPidRef.current
    if (pid != null && wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'device_rename',
        participant_id: pid,
        device_name: n,
      }))
    }
    setEditingName(false)
  }, [participantId])

  // ─── ステータスバー（全状態共通） ─────────────────────────────────────────
  const StatusBar = () => (
    <div className="flex items-center justify-between w-full max-w-sm mb-3 px-1">
      {activeSessionCode && (
        <SessionBadge
          sessionCode={activeSessionCode}
          deviceName={savedDeviceNameRef.current || getDeviceTypeLabel()}
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
    <div className="min-h-screen bg-[var(--ss-bg-app)] text-[var(--ss-t1)] flex flex-col items-center justify-center p-4">
      {/* ロゴ */}
      <div className="mb-4 text-center">
        <div className="inline-flex items-center gap-2 text-[var(--ss-brand)] mb-1">
          <MIcon name="photo_camera" size={24} />
          <span className="text-lg font-bold">{t('app.name')}</span>
        </div>
        <p className="text-[var(--ss-t2)] text-sm">{t('camera_sender.join_title')}</p>
      </div>
      <RecordingProblemNotice state={serverRecorder.state} errorMsg={serverRecorder.errorMsg} />

      {/* ─── State: join ────────────────── */}
      {(senderState === 'join' || (senderState === 'connecting' && !paramCode)) && (
        <div className="w-full max-w-sm bg-[var(--ss-surface-1)] rounded-[6px] p-5 border border-[var(--ss-border)] shadow-[0_1px_2px_rgba(16,24,40,.06)]">
          <div className="space-y-3">
            <div>
              <label htmlFor="cs-join-code" className="block text-xs text-[var(--ss-t2)] mb-1">{t('camera_sender.join_code_label')}</label>
              <input
                id="cs-join-code"
                type="text"
                value={form.sessionCode}
                onChange={(e) => setForm((f) => ({ ...f, sessionCode: e.target.value.toUpperCase() }))}
                placeholder="XXXXXX"
                className="w-full bg-[var(--ss-surface-1)] rounded-[5px] px-3 py-2 text-sm font-mono ss-num text-[var(--ss-t1)] placeholder-[var(--ss-t3)] border border-[var(--ss-border-strong)] focus:outline-none focus:ring-2 focus:ring-[var(--ss-focus-ring)]"
                autoCapitalize="characters"
              />
            </div>
            <div>
              <label htmlFor="cs-join-password" className="block text-xs text-[var(--ss-t2)] mb-1">{t('camera_sender.join_password_label')}</label>
              <input
                id="cs-join-password"
                type="password"
                value={form.password}
                onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
                className="w-full bg-[var(--ss-surface-1)] rounded-[5px] px-3 py-2 text-sm text-[var(--ss-t1)] placeholder-[var(--ss-t3)] border border-[var(--ss-border-strong)] focus:outline-none focus:ring-2 focus:ring-[var(--ss-focus-ring)]"
              />
            </div>
            <div>
              <label htmlFor="cs-join-device" className="block text-xs text-[var(--ss-t2)] mb-1">{t('camera_sender.join_device_label')}</label>
              <input
                id="cs-join-device"
                type="text"
                value={form.deviceName}
                onChange={(e) => setForm((f) => ({ ...f, deviceName: e.target.value }))}
                placeholder={t('auto.CameraSenderPage.k2')}
                className="w-full bg-[var(--ss-surface-1)] rounded-[5px] px-3 py-2 text-sm text-[var(--ss-t1)] placeholder-[var(--ss-t3)] border border-[var(--ss-border-strong)] focus:outline-none focus:ring-2 focus:ring-[var(--ss-focus-ring)]"
              />
            </div>
            {errorMsg && (
              <div className="flex items-center gap-1.5 text-[var(--ss-bad)] text-xs">
                <MIcon name="cancel" size={14} />
                {errorMsg}
              </div>
            )}
            <button
              onClick={() => joinSession(form.sessionCode, form.password, form.deviceName)}
              disabled={!form.sessionCode || !form.password || senderState === 'connecting'}
              className="w-full py-2.5 rounded-[5px] bg-[var(--ss-brand)] hover:bg-[var(--ss-brand-hover)] disabled:opacity-40 disabled:cursor-not-allowed text-sm font-medium text-white inline-flex items-center justify-center gap-2"
            >
              {senderState === 'connecting' && <MIcon name="progress_activity" size={14} className="animate-spin" />}
              {senderState === 'connecting' ? '接続中…' : t('camera_sender.join_button')}
            </button>
          </div>
        </div>
      )}

      {/* ─── State: connecting ──────────── */}
      {senderState === 'connecting' && paramCode && (
        <div className="text-center">
          <MIcon name="progress_activity" size={40} className="animate-spin text-[var(--ss-brand)] mx-auto mb-3" />
          <p className="text-[var(--ss-t2)] text-sm">
            {reconnectCount > 0
              ? `${t('camera_sender.reconnecting')} (${reconnectCount}/${MAX_RECONNECT}${t('camera_sender.reconnect_attempt')})`
              : t('camera_sender.join_connecting')}
          </p>
          {slowConnect && (
            <p className="text-[var(--ss-warn)] text-xs mt-2 max-w-xs mx-auto leading-relaxed">
              {t('camera_sender.slow_connect_hint')}
            </p>
          )}
        </div>
      )}

      {/* ─── State A: 待機 ──────────────── */}
      {senderState === 'state_a' && (
        <div className="w-full max-w-sm flex flex-col items-center">
          <StatusBar />
          <div className="w-full bg-[var(--ss-surface-1)] rounded-[6px] p-8 border border-[var(--ss-border)] shadow-[0_1px_2px_rgba(16,24,40,.06)] text-center">
            <div className="w-16 h-16 rounded-full bg-[var(--ss-brand-tint)] flex items-center justify-center mx-auto mb-4">
              <MIcon name="photo_camera" size={28} className="text-[var(--ss-brand)]" />
            </div>
            <p className="text-lg font-semibold text-[var(--ss-t1)] mb-2">{t('camera_sender.state_a_title')}</p>
            <p className="text-[var(--ss-t2)] text-sm leading-relaxed">{t('camera_sender.state_a_hint')}</p>
            <div className="mt-4 flex items-center justify-center gap-1.5 text-[var(--ss-success)] text-xs">
              <MIcon name="check_circle" size={14} />
              {t('camera_sender.status_connected')}
            </div>
            {/* 端末名表示・編集 */}
            <div className="mt-4 border-t border-[var(--ss-border)] pt-4">
              {editingName ? (
                <div className="flex items-center gap-2">
                  <input
                    autoFocus
                    value={nameInput}
                    onChange={(e) => setNameInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') saveDeviceName(nameInput)
                      if (e.key === 'Escape') setEditingName(false)
                    }}
                    className="flex-1 bg-[var(--ss-surface-2)] rounded-[5px] px-2 py-1 text-sm text-[var(--ss-t1)] text-center border border-[var(--ss-border)] focus:outline-none focus:ring-2 focus:ring-[var(--ss-focus-ring)]"
                    placeholder={getDeviceTypeLabel()}
                    maxLength={32}
                  />
                  <button aria-label={t('app.save')}
                    onClick={() => saveDeviceName(nameInput)}
                    className="p-1 text-[var(--ss-success)] hover:text-[var(--ss-good)]"
                  >
                    <MIcon name="check" size={16} />
                  </button>
                </div>
              ) : (
                <div className="flex items-center justify-center gap-2">
                  <span className="text-xs text-[var(--ss-t3)]">
                    {t('auto.CameraSenderPage.k_device_name_label')} <span className="text-[var(--ss-t1)] font-medium">{savedDeviceNameRef.current || getDeviceTypeLabel()}</span>
                  </span>
                  <button
                    onClick={() => { setNameInput(savedDeviceNameRef.current || getDeviceTypeLabel()); setEditingName(true) }}
                    className="p-1 text-[var(--ss-t3)] hover:text-[var(--ss-t1)] rounded-[5px]"
                    title={t('auto.CameraSenderPage.k1')}
                  >
                    <MIcon name="edit" size={12} />
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
          <div className="w-full bg-[var(--ss-surface-1)] rounded-[6px] p-6 border border-[var(--ss-border)] shadow-[0_1px_2px_rgba(16,24,40,.06)]">
            <div className="w-16 h-16 rounded-full bg-[rgba(178,106,0,0.08)] flex items-center justify-center mx-auto mb-4">
              <MIcon name="photo_camera" size={28} className="text-[var(--ss-warn)]" />
            </div>
            <p className="text-center text-lg font-semibold text-[var(--ss-t1)] mb-2">{t('camera_sender.state_b_title')}</p>
            <p className="text-center text-xs text-[var(--ss-t2)] mb-5">
              {t('auto.CameraSenderPage.k_fix_device')}
            </p>
            {errorMsg && (
              <div className="flex items-start gap-1.5 text-[var(--ss-bad)] text-xs mb-3 bg-[rgba(194,51,74,0.08)] rounded-[5px] p-2 border border-[var(--ss-border)]">
                <MIcon name="cancel" size={14} className="shrink-0 mt-0.5" />
                {errorMsg}
              </div>
            )}
            <div className="space-y-2">
              <button
                onClick={startCamera}
                disabled={startingCamera}
                className="w-full py-3 rounded-[5px] bg-[var(--ss-bad)] hover:bg-[rgba(194,51,74,0.9)] disabled:opacity-60 disabled:cursor-not-allowed text-white font-semibold flex items-center justify-center gap-2"
              >
                {startingCamera ? <MIcon name="progress_activity" size={18} className="animate-spin" /> : <MIcon name="photo_camera" size={18} />}
                {startingCamera ? '起動中…' : t('camera_sender.state_b_start')}
              </button>
              <button
                onClick={() => { setSenderState('state_a'); setErrorMsg('') }}
                className="w-full py-2.5 rounded-[5px] bg-[var(--ss-surface-2)] hover:bg-[var(--ss-surface-3)] text-[var(--ss-t1)] text-sm border border-[var(--ss-border)]"
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
          <div className="relative w-full mb-4 rounded-[6px] overflow-hidden bg-black aspect-video shadow-[0_10px_28px_rgba(16,24,40,.14)]">
            <video
              ref={previewRef}
              autoPlay
              playsInline
              muted
              className="w-full h-full object-cover"
            />
            <div className="absolute top-2 left-2 flex items-center gap-1.5 bg-[var(--ss-bad)] text-white text-xs px-2 py-0.5 rounded-[999px]">
              <span className="w-1.5 h-1.5 rounded-full bg-white animate-pulse" />
              {t('camera_sender.state_c_active')}
            </div>
          </div>
          <p className="text-center text-xs text-[var(--ss-t3)] mb-4">{t('camera_sender.state_c_hint')}</p>
          <button
            onClick={stopCamera}
            className="w-full py-3 rounded-[5px] bg-[var(--ss-surface-2)] hover:bg-[var(--ss-surface-3)] text-[var(--ss-t1)] font-medium flex items-center justify-center gap-2 border border-[var(--ss-border)]"
          >
            <MIcon name="videocam_off" size={18} />
            {t('camera_sender.state_c_stop')}
          </button>
        </div>
      )}

      {/* ─── State: waiting_approval（承認待ち。エラーではない） ───────────────── */}
      {senderState === 'waiting_approval' && (
        <div className="w-full max-w-sm text-center">
          <div className="bg-[var(--ss-surface-1)] rounded-[6px] p-6 border border-[var(--ss-border)] shadow-[0_1px_2px_rgba(16,24,40,.06)]">
            <MIcon name="hourglass_top" size={36} className="text-[var(--ss-brand)] mx-auto mb-3" />
            <p className="text-lg font-semibold text-[var(--ss-t1)] mb-2">{t('camera_sender.waiting_approval_title')}</p>
            <p className="text-[var(--ss-t2)] text-sm leading-relaxed">{t('camera_sender.waiting_approval_hint')}</p>
            <div className="mt-4 flex items-center justify-center gap-1 text-xs text-[var(--ss-t3)]">
              <MIcon name="progress_activity" size={14} className="animate-spin" />
              {t('camera_sender.status_connected')}
            </div>
            <SessionBadge sessionCode={activeSessionCode} deviceName={savedDeviceNameRef.current} />
          </div>
        </div>
      )}

      {/* ─── State: error ───────────────── */}
      {senderState === 'error' && (
        <div className="w-full max-w-sm text-center">
          <div className="bg-[var(--ss-surface-1)] rounded-[6px] p-6 border border-[var(--ss-border)] shadow-[0_1px_2px_rgba(16,24,40,.06)]">
            <MIcon name={showWifiHint ? 'wifi_off' : 'error_outline'} size={36} className="text-[var(--ss-bad)] mx-auto mb-3" />
            <p className="text-sm text-[var(--ss-t2)] mb-1">{errorMsg || t('camera_sender.join_error_network')}</p>
            {showWifiHint && (
              <p className="text-xs text-[var(--ss-t3)] mb-4">
                {t('auto.CameraSenderPage.k_wifi_check')}
              </p>
            )}
            <div className="text-left text-xs text-[var(--ss-t3)] mb-4 mt-1 space-y-1">
              <p className="font-semibold text-[var(--ss-t2)]">{t('camera_sender.error_next_steps_title')}</p>
              <ul className="list-disc list-inside space-y-0.5">
                <li>{t('camera_sender.error_step_password')}</li>
                <li>{t('camera_sender.error_step_wifi')}</li>
                <li>{t('camera_sender.error_step_retry')}</li>
              </ul>
            </div>
            <div className={`flex gap-2 justify-center${showWifiHint ? '' : ' mt-4'}`}>
              <button
                onClick={() => {
                  reconnectCountRef.current = 0
                  setReconnectCount(0)
                  setShowWifiHint(false)
                  const code = savedCodeRef.current
                  const pid = savedPidRef.current
                  if (code && pid) {
                    void connectWs(code, pid)
                  } else {
                    setSenderState('join')
                  }
                }}
                className="px-4 py-2 rounded-[5px] bg-[var(--ss-brand)] hover:bg-[var(--ss-brand-hover)] text-sm text-white font-medium"
              >
                {t('auto.CameraSenderPage.k_retry')}
              </button>
              <button
                onClick={() => { setSenderState('join'); setErrorMsg(''); setShowWifiHint(false) }}
                className="px-4 py-2 rounded-[5px] bg-[var(--ss-surface-2)] hover:bg-[var(--ss-surface-3)] text-sm text-[var(--ss-t1)] border border-[var(--ss-border)]"
              >
                {t('auto.CameraSenderPage.k_restart')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
