/**
 * AnnotatorVideoPane — ローカル動画 + YOLO / TrackNet オーバーレイを包むペイン
 *
 * - videoContainerRef を div に attach: PlayerPositionOverlay / ShuttleTrackOverlay が寸法参照
 * - ROI 矩形オーバーレイ: roiRect / roiEditing / onRoiChange で制御
 * - BBox 描画: video.getBoundingClientRect() でレターボックスオフセットを補正
 */
import { useEffect, useRef, type RefObject } from 'react'
import { VideoPlayer } from '@/components/video/VideoPlayer'
import { PlayerPositionOverlay } from '@/components/annotation/PlayerPositionOverlay'
import { ShuttleTrackOverlay } from '@/components/annotation/ShuttleTrackOverlay'
import { CourtGridOverlay } from '@/components/video/CourtGridOverlay'
import { RoiRectOverlay, type RoiRect } from '@/components/video/RoiRectOverlay'
import type { ShuttleFrame } from '@/components/annotation/ShuttleTrackOverlay'

interface Props {
  videoRef: RefObject<HTMLVideoElement>
  videoContainerRef: RefObject<HTMLDivElement>
  src: string
  playbackRate: number
  onPlaybackRateChange: (rate: number) => void
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  yoloFrames: any[]
  yoloOverlayVisible: boolean
  currentVideoSec: number
  shuttleFrames: ShuttleFrame[]
  shuttleOverlayVisible: boolean
  /** コートグリッドオーバーレイ */
  courtGridMatchId?: string
  courtGridVisible?: boolean
  /** ROI 矩形 */
  roiRect?: RoiRect | null
  roiEditing?: boolean
  onRoiChange?: (rect: RoiRect | null) => void
}

/**
 * video 要素の object-fit:contain レターボックスを考慮した実際の描画領域を返す。
 * 返す値は containerDiv 左上を原点とした px 座標。
 */
function getVideoRenderRect(videoEl: HTMLVideoElement, containerEl: HTMLElement): {
  left: number; top: number; width: number; height: number
} {
  const cw = containerEl.clientWidth
  const ch = containerEl.clientHeight
  const vw = videoEl.videoWidth  || cw
  const vh = videoEl.videoHeight || ch
  const videoAspect     = vw / vh
  const containerAspect = cw / ch
  let renderW: number, renderH: number
  if (videoAspect > containerAspect) {
    renderW = cw
    renderH = cw / videoAspect
  } else {
    renderH = ch
    renderW = ch * videoAspect
  }
  return {
    left:   (cw - renderW) / 2,
    top:    (ch - renderH) / 2,
    width:  renderW,
    height: renderH,
  }
}

export function AnnotatorVideoPane({
  videoRef,
  videoContainerRef,
  src,
  playbackRate,
  onPlaybackRateChange,
  yoloFrames,
  yoloOverlayVisible,
  currentVideoSec,
  shuttleFrames,
  shuttleOverlayVisible,
  courtGridMatchId,
  courtGridVisible = false,
  roiRect = null,
  roiEditing = false,
  onRoiChange,
}: Props) {
  // video の描画領域を追跡するための state
  const renderRectRef = useRef<{ left: number; top: number; width: number; height: number } | null>(null)

  useEffect(() => {
    const video = videoRef.current
    const container = videoContainerRef.current
    if (!video || !container) return
    const update = () => {
      renderRectRef.current = getVideoRenderRect(video, container)
    }
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
  }, [videoRef, videoContainerRef])

  const rr = renderRectRef.current
  const overlayStyle = rr
    ? { position: 'absolute' as const, left: rr.left, top: rr.top, width: rr.width, height: rr.height }
    : { position: 'absolute' as const, inset: 0 }

  return (
    <div ref={videoContainerRef} className="relative w-full">
      <VideoPlayer
        videoRefProp={videoRef}
        src={src}
        playbackRate={playbackRate}
        onPlaybackRateChange={onPlaybackRateChange}
      />
      {/* BBox / シャトル軌跡オーバーレイ — レターボックス補正済み座標に配置 */}
      {yoloFrames.length > 0 && rr && (
        <div style={overlayStyle} className="pointer-events-none">
          <PlayerPositionOverlay
            frames={yoloFrames}
            currentSec={currentVideoSec}
            videoWidth={rr.width}
            videoHeight={rr.height}
            visible={yoloOverlayVisible}
          />
        </div>
      )}
      {shuttleFrames.length > 0 && rr && (
        <div style={overlayStyle} className="pointer-events-none">
          <ShuttleTrackOverlay
            frames={shuttleFrames}
            currentSec={currentVideoSec}
            videoWidth={rr.width}
            videoHeight={rr.height}
            visible={shuttleOverlayVisible}
          />
        </div>
      )}
      {/* コートグリッド */}
      {courtGridMatchId && (
        <CourtGridOverlay
          matchId={courtGridMatchId}
          containerRef={videoContainerRef}
          visible={courtGridVisible}
        />
      )}
      {/* ROI 矩形オーバーレイ */}
      {(roiRect || roiEditing) && onRoiChange && (
        <RoiRectOverlay
          value={roiRect ?? null}
          onChange={onRoiChange}
          editing={roiEditing}
          containerRef={videoContainerRef}
        />
      )}
    </div>
  )
}
