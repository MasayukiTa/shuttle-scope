/**
 * useSessionSharing — リモートセッション・トンネル・カメラストリーム状態を管理するフック
 *
 * 以下の関心を AnnotatorPage から分離する:
 *   - セッション作成・管理（R-001/R-002）
 *   - トンネル起動/停止（cloudflare / ngrok）
 *   - リモートWebRTCストリーム受信（DeviceManagerPanel からの通知）
 *   - ローカルPCカメラストリーム受信
 *   - リモート接続ヘルス状態
 *
 * Note: videoSourceMode の setVideoSourceMode は AnnotatorPage 側で保持する。
 * DeviceManagerPanel のコールバックでストリーム受信時に呼び出す仕組みは
 * AnnotatorPage 側の JSX インライン callbacks に残す（シンプルな1行）。
 */
import { useState, useRef, useEffect, useCallback } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { apiGet, apiPost } from '@/api/client'
import i18n from '@/i18n'

// ── 型定義 ───────────────────────────────────────────────────────────────────

interface ActiveSession {
  session_code: string
  coach_urls: string[]
  camera_sender_urls?: string[]
  session_password?: string
  /** パスワードが設定済みか。再読み込み後も「設定済み」を出すために使う */
  password_set?: boolean
}

interface RemoteHealth {
  wsConnected: boolean
  connectionState: RTCPeerConnectionState | null
  turnInUse: boolean | null
}

type TunnelProvider = 'cloudflare' | 'ngrok'

interface TunnelData {
  available: boolean
  running: boolean
  url: string | null
  active_provider: TunnelProvider | null
  providers: {
    cloudflare: {
      available: boolean
      named_ready?: boolean
      hostname?: string
      config_path?: string | null
      reason?: string | null
    }
    ngrok: { available: boolean }
  }
  recent_log: string[]
}

interface Options {
  matchId: string | undefined
  tunnelProvider: string  // appSettings.tunnel_provider
  /** 共有セッションの作成・取得に失敗したときの通知先 */
  onError?: (message: string) => void
}

export interface SessionSharingResult {
  // セッション
  activeSession: ActiveSession | null
  setActiveSession: React.Dispatch<React.SetStateAction<ActiveSession | null>>
  showSessionModal: boolean
  setShowSessionModal: React.Dispatch<React.SetStateAction<boolean>>
  showDeviceManager: boolean
  setShowDeviceManager: React.Dispatch<React.SetStateAction<boolean>>
  handleCreateOrGetSession: () => Promise<void>
  // トンネル
  tunnelStatus: { success: boolean; data: TunnelData } | undefined
  tunnelToggle: ReturnType<typeof useMutation<unknown, Error, void, unknown>>
  tunnelBase: string | null
  tunnelPending: boolean
  /** トンネル状態の取得が未確定（ロード中/失敗）。true の間はトグルを無効化する */
  tunnelUnconfirmed: boolean
  tunnelLastError: string | null
  rebaseUrl: (url: string) => string
  /** 画面を開いている公開 HTTPS オリジン (localhost / LAN IP でない https)。無ければ null */
  publicOrigin: string | null
  // リモートストリーム
  remoteStream: MediaStream | null
  setRemoteStream: React.Dispatch<React.SetStateAction<MediaStream | null>>
  remoteStreamVideoRef: React.RefObject<HTMLVideoElement>
  // ローカルカメラ
  localCamStream: MediaStream | null
  setLocalCamStream: React.Dispatch<React.SetStateAction<MediaStream | null>>
  localCamVideoRef: React.RefObject<HTMLVideoElement>
  // ヘルス
  remoteHealth: RemoteHealth | null
  setRemoteHealth: React.Dispatch<React.SetStateAction<RemoteHealth | null>>
}

// ── フック本体 ────────────────────────────────────────────────────────────────

export function useSessionSharing({
  matchId,
  tunnelProvider,
  onError,
}: Options): SessionSharingResult {

  // ── セッション ────────────────────────────────────────────────────────────

  const [activeSession, setActiveSession] = useState<ActiveSession | null>(null)
  const [showSessionModal, setShowSessionModal] = useState(false)
  const [showDeviceManager, setShowDeviceManager] = useState(false)

  const handleCreateOrGetSession = useCallback(async () => {
    if (!matchId) return
    try {
      const res = await apiPost<{
        success: boolean
        data: {
          session_code: string
          coach_urls: string[]
          camera_sender_urls?: string[]
          session_password?: string
          password_set?: boolean
        }
      }>('/sessions', { match_id: Number(matchId) })
      if (res.success) {
        setActiveSession({
          session_code: res.data.session_code,
          coach_urls: res.data.coach_urls,
          camera_sender_urls: res.data.camera_sender_urls,
          session_password: res.data.session_password,
          password_set: res.data.password_set,
        })
      } else {
        onError?.(i18n.t('common_ui.share_create_failed'))
      }
    } catch {
      // 通信断・認証切れ・サーバ障害で作成できなかったことを利用者へ知らせる
      onError?.(i18n.t('common_ui.share_create_failed'))
    }
  }, [matchId, onError])

  // ── トンネル ──────────────────────────────────────────────────────────────

  const {
    data: tunnelStatus,
    refetch: refetchTunnel,
    isError: tunnelStatusError,
    isLoading: tunnelStatusLoading,
  } = useQuery({
    queryKey: ['tunnel-status'],
    queryFn: () =>
      apiGet<{ success: boolean; data: TunnelData }>('/tunnel/status'),
    refetchInterval: 5000,
  })

  // 状態取得が未確定（初回ロード中 or 失敗）の間は running を判断できない。
  // false(=停止) と誤認して /tunnel/start を再送すると二重起動になるため、トグルを止める。
  const tunnelUnconfirmed = tunnelStatusLoading || tunnelStatusError || tunnelStatus === undefined

  const tunnelToggle = useMutation({
    mutationFn: () => {
      // 状態未確定のまま start/stop を送らない（停止と誤認した再送を防ぐ）
      if (tunnelUnconfirmed) {
        return Promise.reject(new Error('tunnel status unconfirmed'))
      }
      return tunnelStatus?.data?.running
        ? apiPost('/tunnel/stop', {})
        : apiPost(`/tunnel/start?provider=${tunnelProvider}`, {})
    },
    onSuccess: () => { refetchTunnel() },
  })

  const tunnelRunning = tunnelStatus?.data?.running ?? false
  // tunnelBase の優先順位:
  //   1. backend で起動中の trycloudflare quick tunnel URL
  //   2. named tunnel が config レベルで ready なら hostname (Windows サービスで常駐想定)
  //   3. なし
  const cfNamed = tunnelStatus?.data?.providers?.cloudflare
  const namedReadyHost = cfNamed?.named_ready ? cfNamed.hostname : null
  const tunnelBase: string | null =
    (tunnelRunning && tunnelStatus?.data?.url) ||
    (namedReadyHost ? `https://${namedReadyHost}` : null) ||
    null
  // trueのとき: トンネル起動中だがURLがまだ取得できていない（ポーリング待機中）
  const tunnelPending = tunnelRunning && !tunnelStatus?.data?.url && !namedReadyHost
  // 直近のエラーログ（タイムアウト・認証失敗などのエラーメッセージ）
  const tunnelLastError: string | null = (() => {
    // トンネル URL が取得できている (= 健全) 場合は、過去の benign なログ行を
    // エラーとして誤表示しない (URL あり + spurious error の同時表示を防ぐ)。
    if (tunnelBase) return null
    const log = tunnelStatus?.data?.recent_log ?? []
    // エラー・失敗を示すログエントリを探す（最新から）
    for (let i = log.length - 1; i >= 0; i--) {
      const line = log[i]
      const lower = line.toLowerCase()
      // 'error-free' / 'failed=0' / '0 failed' 等の benign な部分一致を除外。
      const benign =
        lower.includes('error-free') || lower.includes('failed=0') || lower.includes('0 failed')
      if (
        !benign && (
          line.includes('取得できませんでした') ||
          line.includes('終了しました') ||
          line.includes('authtoken') ||
          line.includes('ERR_NGROK') ||
          lower.includes('error') ||
          line.includes('failed')
        )
      ) {
        return line
      }
    }
    return null
  })()

  const rebaseUrl = useCallback((url: string) => {
    if (!tunnelBase) return url
    try {
      const u = new URL(url)
      // localhost / 127.0.0.1 は常にそのまま返す（トンネル経由は不要）
      if (u.hostname === 'localhost' || u.hostname === '127.0.0.1') return url
      // pathname + search + hash を保持してオリジンだけ tunnelBase に置換する
      return tunnelBase + u.pathname + u.search + u.hash
    } catch { return url }
  }, [tunnelBase])

  // 画面を開いている公開 HTTPS オリジン。app.shuttle-scope.com のような公開ドメインで
  // 開いている場合、backend が LAN IP / localhost の URL しか返さなくても、別ネットワーク
  // (携帯回線など) の端末が開ける URL を組み立てるために使う。
  // https かつ localhost / 127.0.0.1 / プライベート LAN IP でないときのみ採用する。
  const publicOrigin: string | null = (() => {
    if (typeof window === 'undefined') return null
    try {
      const { protocol, hostname, origin } = window.location
      if (protocol !== 'https:') return null
      if (hostname === 'localhost' || hostname === '127.0.0.1') return null
      // プライベート / リンクローカルな IPv4 は公開オリジンとみなさない。
      // 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16
      if (/^(10|127)\.|^169\.254\.|^192\.168\.|^172\.(1[6-9]|2[0-9]|3[0-1])\./.test(hostname)) return null
      return origin
    } catch {
      return null
    }
  })()

  // ── リモートストリーム ────────────────────────────────────────────────────

  const [remoteStream, setRemoteStream] = useState<MediaStream | null>(null)
  const remoteStreamVideoRef = useRef<HTMLVideoElement>(null)
  useEffect(() => {
    if (remoteStreamVideoRef.current) {
      remoteStreamVideoRef.current.srcObject = remoteStream
    }
  }, [remoteStream])

  // ── ローカルカメラ ────────────────────────────────────────────────────────

  const [localCamStream, setLocalCamStream] = useState<MediaStream | null>(null)
  const localCamVideoRef = useRef<HTMLVideoElement>(null)
  useEffect(() => {
    if (localCamVideoRef.current) {
      localCamVideoRef.current.srcObject = localCamStream
    }
  }, [localCamStream])

  // ── リモートヘルス ────────────────────────────────────────────────────────

  const [remoteHealth, setRemoteHealth] = useState<RemoteHealth | null>(null)

  // ── 公開 ──────────────────────────────────────────────────────────────────

  return {
    // セッション
    activeSession,
    setActiveSession,
    showSessionModal,
    setShowSessionModal,
    showDeviceManager,
    setShowDeviceManager,
    handleCreateOrGetSession,
    // トンネル
    tunnelStatus,
    tunnelToggle,
    tunnelBase,
    tunnelPending,
    tunnelUnconfirmed,
    tunnelLastError,
    rebaseUrl,
    publicOrigin,
    // リモートストリーム
    remoteStream,
    setRemoteStream,
    remoteStreamVideoRef,
    // ローカルカメラ
    localCamStream,
    setLocalCamStream,
    localCamVideoRef,
    // ヘルス
    remoteHealth,
    setRemoteHealth,
  }
}
