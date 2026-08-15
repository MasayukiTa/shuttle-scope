/**
 * リモートビューワーページ — PC / タブレット向け
 *
 * オペレーター PC が iOS カメラから受けた映像ストリームを
 * WebRTC 経由で転送受信して表示する。
 *
 * 接続フロー:
 *   join → POST /sessions/{code}/join (role=viewer) → participant_token
 *        → POST /sessions/{code}/ws-ticket        → 30 秒の入場券
 *        → WS /ws/camera/{code}?ticket={ticket}
 *        → operator が viewer_webrtc_offer を送信
 *        → RTCPeerConnection で受信・表示
 *
 * 再接続: WS 切断後 5 秒で自動再接続（最大 5 回）
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams, useLocation } from 'react-router-dom'
import { apiPost, apiGet } from '@/api/client'
import { useDeviceHeartbeat } from '@/hooks/useDeviceHeartbeat'
import { useTranslation } from 'react-i18next'
import { MIcon } from '@/components/common/MIcon'
import { participantWsUrl } from '@/utils/cameraWs'
import { getDeviceUid } from '@/utils/deviceUid'

type ViewerState = 'join' | 'connecting' | 'waiting' | 'receiving' | 'error'

const MAX_RECONNECT = 5
const RECONNECT_DELAY_MS = 5_000
const VIEWER_NAME_KEY = 'ss_viewer_name'

export function ViewerPage() {
  const { t } = useTranslation()
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
  // join で一度だけ返る参加者トークン。WS 入場券の引き換えに使う。
  const savedTokenRef = useRef('')
  // 入場券取得の await 中にアンマウントされたら WS を開かないための番人
  const disposedRef = useRef(false)

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
      void connectWs(code, pid)
    }, RECONNECT_DELAY_MS)
    // connectWs is defined below (mutually recursive callbacks)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ─── WebSocket 接続 ───────────────────────────────────────────────────────
   
  const connectWs = useCallback(async (code: string, pid: number) => {
    if (wsRef.current) {
      wsRef.current.onclose = null
      wsRef.current.close()
      wsRef.current = null
    }

    // camera review #1 fix: サーバは `viewer_id` を読む (旧 `vid` は互換で受理)。
    // 入場券経路では role / viewer_id は入場券に刻まれた値が使われる。
    let wsUrl: string
    try {
      wsUrl = await participantWsUrl(code, 'viewer', pid, savedTokenRef.current)
    } catch {
      scheduleReconnect(code, pid)
      return
    }
    if (disposedRef.current) return

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
        data: {
          participant_id: number; session_code: string
          participant_token?: string
        }
      }>(`/sessions/${code}/join`, {
        role: 'viewer',
        device_name: name,
        device_type: 'pc',
        device_uid: getDeviceUid(),
        session_password: password || undefined,
      })
      if (!res.success) throw new Error('join failed')
      const pid = res.data.participant_id
      setParticipantId(pid)
      savedPidRef.current = pid
      // WS 入場券の引き換えに使う。平文はこの応答でしか返らない。
      savedTokenRef.current = res.data.participant_token ?? ''
      setActiveSessionCode(code)
      reconnectCountRef.current = 0
      void connectWs(code, pid)
    } catch (err: unknown) {
      const status = errorStatus(err)
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
    // StrictMode は setup → cleanup → setup と二度走る。ここで false に
    // 戻さないと、二度目以降の接続が入場券取得後に必ず中止される。
    disposedRef.current = false
    return () => {
      disposedRef.current = true
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
      pcRef.current?.close()
      if (wsRef.current?.onclose) wsRef.current.onclose = null
      wsRef.current?.close()
    }
  }, [])

  // ─── レンダリング ──────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-[var(--ss-bg-app)] text-[var(--ss-t1)] flex flex-col items-center justify-center p-4">
      {/* ロゴ */}
      <div className="mb-4 text-center">
        <div className="inline-flex items-center gap-2 text-[var(--ss-brand)] mb-1">
          <MIcon name="visibility" size={24} />
          <span className="text-lg font-bold">{t('app.name')}</span>
        </div>
        <p className="text-[var(--ss-t2)] text-sm">{t('auto.ViewerPage.k1')}</p>
        <p className="text-[var(--ss-t3)] text-xs mt-1">{t('auto.ViewerPage.k2')}</p>
      </div>

      {/* ─── State: join ── */}
      {(viewerState === 'join' || (viewerState === 'connecting' && !paramCode)) && (
        <div className="w-full max-w-sm bg-[var(--ss-surface-1)] rounded-[6px] p-5 border border-[var(--ss-border)] shadow-[0_1px_2px_rgba(16,24,40,.06)]">
          <div className="space-y-3">
            <div>
              <label className="block text-xs text-[var(--ss-t2)] mb-1">{t('auto.ViewerPage.k3')}</label>
              <input
                type="text"
                value={form.sessionCode}
                onChange={(e) => setForm((f) => ({ ...f, sessionCode: e.target.value.toUpperCase() }))}
                placeholder="XXXXXX"
                className="w-full bg-[var(--ss-surface-1)] rounded-[5px] px-3 py-2 text-sm font-mono text-[var(--ss-t1)] placeholder-[var(--ss-t3)] border border-[var(--ss-border-strong)] focus:outline-none focus:ring-2 focus:ring-[var(--ss-focus-ring)]"
                autoCapitalize="characters"
              />
            </div>
            <div>
              <label className="block text-xs text-[var(--ss-t2)] mb-1">{t('auto.ViewerPage.k4')}</label>
              <input
                type="password"
                value={form.password}
                onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
                className="w-full bg-[var(--ss-surface-1)] rounded-[5px] px-3 py-2 text-sm text-[var(--ss-t1)] placeholder-[var(--ss-t3)] border border-[var(--ss-border-strong)] focus:outline-none focus:ring-2 focus:ring-[var(--ss-focus-ring)]"
              />
            </div>
            <div>
              <label className="block text-xs text-[var(--ss-t2)] mb-1">{t('auto.ViewerPage.k5')}</label>
              <input
                type="text"
                value={form.viewerName}
                onChange={(e) => setForm((f) => ({ ...f, viewerName: e.target.value }))}
                placeholder={t('auto.ViewerPage.k8')}
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
              onClick={() => joinSession(form.sessionCode, form.password, form.viewerName)}
              disabled={!form.sessionCode}
              className="w-full py-2.5 rounded-[5px] bg-[var(--ss-brand)] hover:bg-[var(--ss-brand-hover)] disabled:opacity-40 disabled:cursor-not-allowed text-sm font-medium text-white"
            >
              {t('auto.ViewerPage.k9')}
            </button>
          </div>
        </div>
      )}

      {/* ─── State: connecting ── */}
      {viewerState === 'connecting' && paramCode && (
        <div className="text-center">
          <MIcon name="progress_activity" size={40} className="animate-spin text-[var(--ss-brand)] mx-auto mb-3" />
          <p className="text-[var(--ss-t2)] text-sm">
            {reconnectCount > 0
              ? `再接続中... (${reconnectCount}/${MAX_RECONNECT})`
              : 'セッションに接続中...'}
          </p>
        </div>
      )}

      {/* ─── State: waiting ── */}
      {viewerState === 'waiting' && (
        <div className="w-full max-w-sm bg-[var(--ss-surface-1)] rounded-[6px] p-8 text-center border border-[var(--ss-border)] shadow-[0_1px_2px_rgba(16,24,40,.06)]">
          <div className="w-16 h-16 rounded-full bg-[var(--ss-brand-tint)] flex items-center justify-center mx-auto mb-4">
            <MIcon name="visibility" size={28} className="text-[var(--ss-brand)]" />
          </div>
          <p className="text-lg font-semibold text-[var(--ss-t1)] mb-2">{t('auto.ViewerPage.k6')}</p>
          <p className="text-[var(--ss-t2)] text-sm leading-relaxed">
            {t('auto.ViewerPage.k10')}
          </p>
          <div className="mt-4 flex items-center justify-center gap-1.5 text-[var(--ss-success)] text-xs">
            <MIcon name="check_circle" size={14} />
            {t('auto.ViewerPage.k11')}
            {reconnectCount > 0 && (
              <span className="text-[var(--ss-t3)] ml-1">{t('auto.ViewerPage.k12', { n: reconnectCount })}</span>
            )}
          </div>
          <p className="mt-4 text-[var(--ss-t3)] text-xs">
            {t('auto.ViewerPage.k13')}
          </p>
        </div>
      )}

      {/* ─── State: receiving ── */}
      {viewerState === 'receiving' && (
        <div className="w-full max-w-2xl flex flex-col items-center">
          <div className="relative w-full rounded-[6px] overflow-hidden bg-black aspect-video shadow-[0_10px_28px_rgba(16,24,40,.14)]">
            <video
              ref={videoRef}
              autoPlay
              playsInline
              className="w-full h-full object-contain"
            />
            <div className="absolute top-2 left-2 flex items-center gap-1.5 bg-[var(--ss-bad)] text-white text-xs px-2 py-0.5 rounded-[999px]">
              <span className="w-1.5 h-1.5 rounded-full bg-white animate-pulse" />
              {t('auto.ViewerPage.k14')}
            </div>
          </div>
          <div className="mt-3 flex items-center gap-2 text-xs text-[var(--ss-t3)]">
            <MIcon name="videocam" size={12} />
            <span>{t('auto.ViewerPage.k7')}</span>
            {activeSessionCode && (
              <span className="font-mono ss-num text-[var(--ss-t2)]">#{activeSessionCode}</span>
            )}
          </div>
        </div>
      )}

      {/* ─── State: error ── */}
      {viewerState === 'error' && (
        <div className="w-full max-w-sm text-center">
          <div className="bg-[var(--ss-surface-1)] rounded-[6px] p-6 border border-[var(--ss-border)] shadow-[0_1px_2px_rgba(16,24,40,.06)]">
            <MIcon name="wifi_off" size={36} className="text-[var(--ss-bad)] mx-auto mb-3" />
            <p className="text-sm text-[var(--ss-t2)] mb-4">{errorMsg || '接続に失敗しました。'}</p>
            <div className="flex gap-2 justify-center">
              <button
                onClick={() => {
                  reconnectCountRef.current = 0
                  setReconnectCount(0)
                  const code = savedCodeRef.current
                  const pid = savedPidRef.current
                  if (code && pid) {
                    setViewerState('connecting')
                    void connectWs(code, pid)
                  } else {
                    setViewerState('join')
                    setErrorMsg('')
                  }
                }}
                className="px-4 py-2 rounded-[5px] bg-[var(--ss-brand)] hover:bg-[var(--ss-brand-hover)] text-sm text-white font-medium"
              >
                {t('auto.ViewerPage.k15')}
              </button>
              <button
                onClick={() => { setViewerState('join'); setErrorMsg('') }}
                className="px-4 py-2 rounded-[5px] bg-[var(--ss-surface-2)] hover:bg-[var(--ss-surface-3)] text-sm text-[var(--ss-t1)] border border-[var(--ss-border)]"
              >
                {t('auto.ViewerPage.k16')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
