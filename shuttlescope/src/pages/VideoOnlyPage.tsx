/**
 * VideoOnlyPage — 別モニタ用「動画ペイン完全ミラー」
 *
 * screen-capture ではなくネイティブ描画でミラーする:
 * 1. IPC `mirror-message` で {src, visible flags, overlay data} と
 *    {currentSec, isPaused, playbackRate} を受信
 * 2. <video src={同じURL}> をネイティブ再生し currentTime を同期
 * 3. オーバーレイ（BBox/軌跡/グリッド/ROI/選手識別）はメインと同一データで再描画
 *
 * 結果: 高解像度モニタでも画質劣化なし。BBOX/グリッド/ROI は同じデータから
 * 同じ currentSec で描画するので構造的にメインと一致する。
 */
import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { PlayerPositionOverlay } from '@/components/annotation/PlayerPositionOverlay'
import { ShuttleTrackOverlay, type ShuttleFrame } from '@/components/annotation/ShuttleTrackOverlay'
import { CourtGridOverlay } from '@/components/video/CourtGridOverlay'
import { RoiRectOverlay, type RoiRect } from '@/components/video/RoiRectOverlay'
import { PlayerTrackingOverlay, type TrackFrame, type RawDetection } from '@/components/annotation/PlayerTrackingOverlay'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type YoloFrame = any

interface DataMsg {
  type: 'data'
  src: string
  yoloFrames: YoloFrame[]
  shuttleFrames: ShuttleFrame[]
  trackFrames: TrackFrame[]
  frameDetections: RawDetection[]
  roiRect: RoiRect | null
  courtGridMatchId: string | null
  yoloOverlayVisible: boolean
  shuttleOverlayVisible: boolean
  courtGridVisible: boolean
  trackingVisible: boolean
}
interface TickMsg {
  type: 'tick'
  currentSec: number
  isPaused: boolean
  playbackRate: number
}

function getVideoRenderRect(videoEl: HTMLVideoElement, containerEl: HTMLElement) {
  const cw = containerEl.clientWidth
  const ch = containerEl.clientHeight
  const vw = videoEl.videoWidth || cw
  const vh = videoEl.videoHeight || ch
  const videoAspect = vw / vh
  const containerAspect = cw / ch
  let renderW: number, renderH: number
  if (videoAspect > containerAspect) { renderW = cw; renderH = cw / videoAspect }
  else { renderH = ch; renderW = ch * videoAspect }
  return { left: (cw - renderW) / 2, top: (ch - renderH) / 2, width: renderW, height: renderH }
}

export function VideoOnlyPage() {
  const videoRef = useRef<HTMLVideoElement>(null)
  const areaRef = useRef<HTMLDivElement>(null)

  const [data, setData] = useState<DataMsg | null>(null)
  const [tick, setTick] = useState<TickMsg>({ type: 'tick', currentSec: 0, isPaused: true, playbackRate: 1 })
  const [rr, setRr] = useState<{ left: number; top: number; width: number; height: number } | null>(null)

  // ── IPC 購読 ──────────────────────────────────────────────────────────────
  useEffect(() => {
    const subscribe = window.shuttlescope?.onMirror
    const send = window.shuttlescope?.sendMirror
    if (!subscribe) return
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const unsub = subscribe((p: any) => {
      if (p?.type === 'data') setData(p as DataMsg)
      else if (p?.type === 'tick') setTick(p as TickMsg)
    })
    // マウント直後に現状要求（ホスト側は最新の data/tick を即返す）
    if (send) send({ type: 'request-state' })
    return () => { unsub() }
  }, [])

  // ── 再生状態同期 ──────────────────────────────────────────────────────────
  useEffect(() => {
    const v = videoRef.current
    if (!v) return
    v.playbackRate = tick.playbackRate || 1
    const drift = Math.abs(v.currentTime - tick.currentSec)
    // 大きいずれ（seek）または一時停止中の手動移動はすぐ揃える
    if (drift > 0.25 || tick.isPaused) {
      try { v.currentTime = tick.currentSec } catch { /* ignore */ }
    }
    if (tick.isPaused) { v.pause() }
    else { v.play().catch(() => {}) }
  }, [tick])

  // ── video 描画矩形追跡（レターボックス補正）─────────────────────────────
  useEffect(() => {
    const v = videoRef.current
    const c = areaRef.current
    if (!v || !c) return
    const update = () => {
      const next = getVideoRenderRect(v, c)
      setRr((prev) => (
        prev &&
        Math.abs(prev.left - next.left) < 0.5 &&
        Math.abs(prev.top - next.top) < 0.5 &&
        Math.abs(prev.width - next.width) < 0.5 &&
        Math.abs(prev.height - next.height) < 0.5
      ) ? prev : next)
    }
    v.addEventListener('loadedmetadata', update)
    v.addEventListener('resize', update)
    const ro = new ResizeObserver(update)
    ro.observe(c)
    update()
    return () => {
      v.removeEventListener('loadedmetadata', update)
      v.removeEventListener('resize', update)
      ro.disconnect()
    }
  }, [data?.src])

  const overlayStyle: CSSProperties = rr
    ? { position: 'absolute', left: rr.left, top: rr.top, width: rr.width, height: rr.height }
    : { position: 'absolute', inset: 0 }

  const noop = () => {}

  return (
    <div className="w-screen h-screen bg-black overflow-hidden">
      <div ref={areaRef} className="relative w-full h-full">
        {data?.src && (
          <video
            ref={videoRef}
            src={data.src}
            className="w-full h-full object-contain bg-black"
            autoPlay
            playsInline
            muted
          />
        )}
        {data && rr && data.yoloFrames.length > 0 && (
          <div style={overlayStyle} className="pointer-events-none">
            <PlayerPositionOverlay
              frames={data.yoloFrames}
              currentSec={tick.currentSec}
              videoWidth={rr.width}
              videoHeight={rr.height}
              visible={data.yoloOverlayVisible}
            />
          </div>
        )}
        {data && rr && data.shuttleFrames.length > 0 && (
          <div style={overlayStyle} className="pointer-events-none">
            <ShuttleTrackOverlay
              frames={data.shuttleFrames}
              currentSec={tick.currentSec}
              videoWidth={rr.width}
              videoHeight={rr.height}
              visible={data.shuttleOverlayVisible}
            />
          </div>
        )}
        {data?.courtGridMatchId && (
          <CourtGridOverlay
            matchId={data.courtGridMatchId}
            containerRef={areaRef}
            visible={data.courtGridVisible}
          />
        )}
        {data?.roiRect && (
          <RoiRectOverlay
            value={data.roiRect}
            onChange={noop}
            editing={false}
            containerRef={areaRef}
          />
        )}
        {data && rr && data.trackingVisible && (
          <div style={overlayStyle} className="pointer-events-none">
            <PlayerTrackingOverlay
              trackFrames={data.trackFrames}
              frameDetections={data.frameDetections}
              currentSec={tick.currentSec}
              isPaused={tick.isPaused}
              visible={data.trackingVisible}
              tagging={false}
              playerOptions={[]}
              onAssign={noop}
              assignments={{}}
            />
          </div>
        )}
      </div>
    </div>
  )
}
