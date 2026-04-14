/**
 * AnnotatorVideoPane — ローカル動画 + YOLO / TrackNet オーバーレイを包むペイン
 *
 * - videoContainerRef を div に attach: PlayerPositionOverlay / ShuttleTrackOverlay が寸法参照
 * - ROI 矩形オーバーレイ: roiRect / roiEditing / onRoiChange で制御
 * - BBox 描画: video.getBoundingClientRect() でレターボックスオフセットを補正
 */
import { useEffect, useRef, type RefObject, type ReactNode } from 'react'
import { VideoPlayer } from '@/components/video/VideoPlayer'
import { PlayerPositionOverlay } from '@/components/annotation/PlayerPositionOverlay'
import { ShuttleTrackOverlay } from '@/components/annotation/ShuttleTrackOverlay'
import { CourtGridOverlay } from '@/components/video/CourtGridOverlay'
import { RoiRectOverlay, type RoiRect } from '@/components/video/RoiRectOverlay'
import type { ShuttleFrame } from '@/components/annotation/ShuttleTrackOverlay'
import { PlayerTrackingOverlay } from '@/components/annotation/PlayerTrackingOverlay'
import type { TrackFrame, RawDetection, PlayerOption } from '@/components/annotation/PlayerTrackingOverlay'

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
  onCalibrationSaved?: () => void
  onCalibSourceChange?: (source: 'backend' | 'local' | 'none') => void
  /** ROI 矩形 */
  roiRect?: RoiRect | null
  roiEditing?: boolean
  onRoiChange?: (rect: RoiRect | null) => void
  /** 選手識別トラッキングオーバーレイ */
  trackFrames?: TrackFrame[]
  frameDetections?: RawDetection[]
  trackingVisible?: boolean
  taggingMode?: boolean
  playerOptions?: PlayerOption[]
  taggingAssignments?: Record<number, string>
  onTagAssign?: (detectionIndex: number, playerKey: string) => void
  isPaused?: boolean
  isLight?: boolean
  /** フレーム検出APIエラー（nullなら正常） */
  frameDetectError?: string | null
  /** フレーム検出デバッグ情報 */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  frameDetectDebug?: Record<string, any> | null
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
  trackFrames = [],
  frameDetections = [],
  trackingVisible = false,
  taggingMode = false,
  playerOptions = [],
  taggingAssignments = {},
  onTagAssign,
  isPaused = false,
  isLight = false,
  frameDetectError,
  frameDetectDebug,
  onCalibrationSaved,
  onCalibSourceChange,
}: Props) {
  // videoAreaRef はビデオ本体 div（aspect-ratio ボックス）を指す。
  // オーバーレイはここに配置 — コントロール（シークバー・ボタン）は含まない。
  const videoAreaRef = useRef<HTMLDivElement>(null)

  // video の描画領域を追跡（レターボックス補正用）
  const renderRectRef = useRef<{ left: number; top: number; width: number; height: number } | null>(null)

  useEffect(() => {
    const video = videoRef.current
    const container = videoAreaRef.current
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
  }, [videoRef])

  const rr = renderRectRef.current
  const overlayStyle = rr
    ? { position: 'absolute' as const, left: rr.left, top: rr.top, width: rr.width, height: rr.height }
    : { position: 'absolute' as const, inset: 0 }

  // オーバーレイ群を ReactNode として構築し VideoPlayer に渡す。
  // VideoPlayer の aspectRatio ボックス内に描画されるため、
  // コントロール（シークバー・再生ボタン等）にはかからない。
  const overlays: ReactNode = (
    <>
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
          containerRef={videoAreaRef}
          visible={courtGridVisible}
          onCalibrationSaved={onCalibrationSaved}
          onCalibSourceChange={onCalibSourceChange}
        />
      )}
      {/* ROI 矩形オーバーレイ */}
      {(roiRect || roiEditing) && onRoiChange && (
        <RoiRectOverlay
          value={roiRect ?? null}
          onChange={onRoiChange}
          editing={roiEditing}
          containerRef={videoAreaRef}
        />
      )}
      {/* 選手識別トラッキングオーバーレイ */}
      {(taggingMode || trackingVisible) && rr && (
        <div style={overlayStyle}>
          <PlayerTrackingOverlay
            trackFrames={trackFrames}
            frameDetections={frameDetections}
            currentSec={currentVideoSec}
            isPaused={isPaused}
            visible={taggingMode || trackingVisible}
            tagging={taggingMode}
            playerOptions={playerOptions}
            onAssign={onTagAssign ?? (() => {})}
            assignments={taggingAssignments}
            isLight={isLight}
            frameDetectError={frameDetectError}
            frameDetectDebug={frameDetectDebug}
          />
        </div>
      )}
    </>
  )

  return (
    <div ref={videoContainerRef} className="w-full">
      <VideoPlayer
        videoRefProp={videoRef}
        src={src}
        playbackRate={playbackRate}
        onPlaybackRateChange={onPlaybackRateChange}
        videoAreaRef={videoAreaRef}
        overlays={overlays}
      />
    </div>
  )
}
