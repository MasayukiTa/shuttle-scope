/**
 * VideoOnlyPage — 別モニタ用フルスクリーン動画表示（メイン状態のミラー）
 *
 * 設計: 別モニタは「画面拡張」であり、独自に解析データを取りに行かない。
 * メインの AnnotatorPage が BroadcastChannel('shuttlescope-video-mirror')
 * 経由で時刻・再生状態・yoloFrames・trackFrames・roiRect を流し、こちら側は
 * 受信して描画＋video の seek/play/pause を追従させるだけ。
 *
 * 選手名解決のため `/matches/{id}` のみ取得する（試合中に変化しないので 1 回）。
 */
import { useRef, useEffect, useState, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { WebViewPlayer } from '@/components/video/WebViewPlayer'
import { PlayerPositionOverlay } from '@/components/annotation/PlayerPositionOverlay'
import { PlayerTrackingOverlay, type TrackFrame, type PlayerOption } from '@/components/annotation/PlayerTrackingOverlay'
import { CourtGridOverlay } from '@/components/video/CourtGridOverlay'
import { RoiRectOverlay, type RoiRect } from '@/components/video/RoiRectOverlay'
import { apiGet } from '@/api/client'

const STREAMING_DOMAINS = [
  'youtube.com', 'youtu.be', 'twitter.com', 'x.com',
  'instagram.com', 'tiktok.com', 'bilibili.com', 'nicovideo.jp',
  'twitch.tv', 'vimeo.com', 'dailymotion.com', 'facebook.com',
]

function isStreamingUrl(url: string): boolean {
  if (!url) return false
  if (url.startsWith('localfile://')) return false
  if (STREAMING_DOMAINS.some((d) => url.includes(d))) return true
  if (url.startsWith('http://') || url.startsWith('https://')) return true
  return false
}

function getVideoRenderRect(videoEl: HTMLVideoElement, containerEl: HTMLElement) {
  const cw = containerEl.clientWidth
  const ch = containerEl.clientHeight
  const vw = videoEl.videoWidth || cw
  const vh = videoEl.videoHeight || ch
  const va = vw / vh
  const ca = cw / ch
  let rw: number, rh: number
  if (va > ca) { rw = cw; rh = cw / va } else { rh = ch; rw = ch * va }
  return { left: (cw - rw) / 2, top: (ch - rh) / 2, width: rw, height: rh }
}

interface MatchPlayer { id: number; name: string }
interface MatchData {
  id: number
  player_a?: MatchPlayer | null; player_b?: MatchPlayer | null
  partner_a?: MatchPlayer | null; partner_b?: MatchPlayer | null
}

// 同じ秒数で何度も seek を撃たないためのしきい値
const SEEK_EPSILON_SEC = 0.15

export function VideoOnlyPage() {
  const [searchParams] = useSearchParams()
  const src = searchParams.get('src') ?? ''
  const startTime = parseFloat(searchParams.get('t') ?? '0')
  const startPaused = searchParams.get('paused') === '1'
  const matchId = searchParams.get('matchId') ?? ''
  const videoRef = useRef<HTMLVideoElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const overlayBoxRef = useRef<HTMLDivElement>(null)

  const [currentSec, setCurrentSec] = useState(startTime)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [yoloFrames, setYoloFrames] = useState<any[]>([])
  const [trackFrames, setTrackFrames] = useState<TrackFrame[]>([])
  const [roiRect, setRoiRect] = useState<RoiRect | null>(null)
  const [match, setMatch] = useState<MatchData | null>(null)
  const [rr, setRr] = useState<{ left: number; top: number; width: number; height: number } | null>(null)

  // ── BroadcastChannel: メイン状態をミラー ────────────────────────────────────
  useEffect(() => {
    const ch = new BroadcastChannel('shuttlescope-video-mirror')
    const onMsg = (ev: MessageEvent) => {
      const msg = ev.data
      if (!msg || typeof msg !== 'object') return
      if (msg.type === 'state') {
        const v = videoRef.current
        if (v) {
          if (Math.abs((v.currentTime ?? 0) - msg.sec) > SEEK_EPSILON_SEC) {
            try { v.currentTime = msg.sec } catch { /* noop */ }
          }
          if (msg.paused && !v.paused) v.pause()
          else if (!msg.paused && v.paused) v.play().catch(() => {})
        }
        setCurrentSec(msg.sec)
      } else if (msg.type === 'data') {
        if (Array.isArray(msg.yoloFrames))  setYoloFrames(msg.yoloFrames)
        if (Array.isArray(msg.trackFrames)) setTrackFrames(msg.trackFrames)
        setRoiRect(msg.roiRect ?? null)
      }
    }
    ch.addEventListener('message', onMsg)
    // 接続直後にメインへ初期状態を要求
    ch.postMessage({ type: 'request-sync' })
    return () => {
      ch.removeEventListener('message', onMsg)
      ch.close()
    }
  }, [])

  // ── 動画初期化 ─────────────────────────────────────────────────────────────
  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    const onLoaded = () => {
      if (startTime > 0) video.currentTime = startTime
      if (!startPaused) video.play().catch(() => {})
    }
    video.addEventListener('loadedmetadata', onLoaded)
    return () => video.removeEventListener('loadedmetadata', onLoaded)
  }, [src, startTime, startPaused])

  // ── レターボックス追従 ───────────────────────────────────────────────────────
  useEffect(() => {
    const video = videoRef.current
    const container = containerRef.current
    if (!video || !container) return
    const update = () => setRr(getVideoRenderRect(video, container))
    video.addEventListener('loadedmetadata', update)
    video.addEventListener('resize', update)
    const ro = new ResizeObserver(update)
    ro.observe(container)
    update()
    return () => {
      video.removeEventListener('loadedmetadata', update)
      video.removeEventListener('resize', update)
      ro.disconnect()
    }
  }, [src])

  // ── 試合情報のみ API 取得（選手名ラベル用） ──────────────────────────────
  useEffect(() => {
    if (!matchId) return
    let cancelled = false
    apiGet<{ success: boolean; data: MatchData }>(`/matches/${matchId}`)
      .then((m) => { if (!cancelled && m.success) setMatch(m.data) })
      .catch(() => { /* noop */ })
    return () => { cancelled = true }
  }, [matchId])

  const playerOptions: PlayerOption[] = useMemo(() => {
    if (!match) return []
    const opts: PlayerOption[] = []
    if (match.player_a)  opts.push({ key: 'player_a',  name: match.player_a.name })
    if (match.partner_a) opts.push({ key: 'partner_a', name: match.partner_a.name })
    if (match.player_b)  opts.push({ key: 'player_b',  name: match.player_b.name })
    if (match.partner_b) opts.push({ key: 'partner_b', name: match.partner_b.name })
    opts.push({ key: 'other', name: 'その他' })
    return opts
  }, [match])

  if (!src) {
    return (
      <div className="flex items-center justify-center w-screen h-screen bg-black text-gray-500 text-sm">
        動画ソースが指定されていません
      </div>
    )
  }

  if (isStreamingUrl(src)) {
    return (
      <div className="w-screen h-screen bg-black overflow-hidden">
        <WebViewPlayer url={src} siteName="動画" />
      </div>
    )
  }

  const overlayStyle = rr
    ? { position: 'absolute' as const, left: rr.left, top: rr.top, width: rr.width, height: rr.height }
    : { position: 'absolute' as const, inset: 0 }

  return (
    <div
      ref={containerRef}
      className="relative w-screen h-screen bg-black overflow-hidden flex items-center justify-center"
    >
      {/* 別モニタ側の video はメイン操作の従属 — controls 非表示 */}
      <video
        ref={videoRef}
        src={src}
        className="w-full h-full object-contain"
        playsInline
        muted
      />
      {/* レターボックス内の透明ボックス（ROI / グリッド用 containerRef） */}
      {rr && (
        <div ref={overlayBoxRef} style={overlayStyle} className="pointer-events-none" />
      )}
      {matchId && yoloFrames.length > 0 && rr && (
        <div style={overlayStyle} className="pointer-events-none">
          <PlayerPositionOverlay
            frames={yoloFrames}
            currentSec={currentSec}
            videoWidth={rr.width}
            videoHeight={rr.height}
            visible={true}
          />
        </div>
      )}
      {matchId && trackFrames.length > 0 && rr && (
        <div style={overlayStyle} className="pointer-events-none">
          <PlayerTrackingOverlay
            trackFrames={trackFrames}
            frameDetections={[]}
            currentSec={currentSec}
            isPaused={false}
            visible={true}
            tagging={false}
            playerOptions={playerOptions}
            onAssign={() => {}}
            assignments={{}}
            isLight={false}
          />
        </div>
      )}
      {matchId && roiRect && rr && (
        <div style={overlayStyle} className="pointer-events-none">
          <RoiRectOverlay
            value={roiRect}
            onChange={() => {}}
            editing={false}
            containerRef={overlayBoxRef}
          />
        </div>
      )}
      {matchId && rr && (
        <div style={overlayStyle} className="pointer-events-none">
          <CourtGridOverlay
            matchId={matchId}
            containerRef={overlayBoxRef}
            visible={true}
          />
        </div>
      )}
    </div>
  )
}
