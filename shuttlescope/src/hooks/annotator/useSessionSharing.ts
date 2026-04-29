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
import { useQuery, useMutation, QueryClient } from '@tanstack/react-query'
import { apiGet, apiPost } from '@/api/client'

// ── 型定義 ───────────────────────────────────────────────────────────────────

interface ActiveSession {
  session_code: string
  coach_urls: string[]
  camera_sender_urls?: string[]
  session_password?: string
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
  tunnelLastError: string | null
  rebaseUrl: (url: string) => string
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
        }
      }>('/sessions', { match_id: Number(matchId) })
      if (res.success) {
        setActiveSession({
          session_code: res.data.session_code,
          coach_urls: res.data.coach_urls,
          camera_sender_urls: res.data.camera_sender_urls,
          session_password: res.data.session_password,
        })
      }
    } catch { /* ignore */ }
  }, [matchId])

  // ── トンネル ──────────────────────────────────────────────────────────────

  const { data: tunnelStatus, refetch: refetchTunnel } = useQuery({
    queryKey: ['tunnel-status'],
    queryFn: () =>
      apiGet<{ success: boolean; data: TunnelData }>('/tunnel/status'),
    refetchInterval: 5000,
  })

  const tunnelToggle = useMutation({
    mutationFn: () =>
      tunnelStatus?.data?.running
        ? apiPost('/tunnel/stop', {})
        : apiPost(`/tunnel/start?provider=${tunnelProvider}`, {}),
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
    const log = tunnelStatus?.data?.recent_log ?? []
    // エラー・失敗を示すログエントリを探す（最新から）
    for (let i = log.length - 1; i >= 0; i--) {
      const line = log[i]
      if (
        line.includes('取得できませんでした') ||
        line.includes('終了しました') ||
        line.includes('authtoken') ||
        line.includes('ERR_NGROK') ||
        line.includes('error') ||
        line.includes('Error') ||
        line.includes('failed')
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
    tunnelLastError,
    rebaseUrl,
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
