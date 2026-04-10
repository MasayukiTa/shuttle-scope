/**
 * AnnotatorVideoPane — ローカル動画 + YOLO / TrackNet オーバーレイを包むペイン
 *
 * videoContainerRef を div に attach することで、
 * PlayerPositionOverlay / ShuttleTrackOverlay がコンテナ寸法を参照できる。
 */
import type { RefObject } from 'react'
import { VideoPlayer } from '@/components/video/VideoPlayer'
import { PlayerPositionOverlay } from '@/components/annotation/PlayerPositionOverlay'
import { ShuttleTrackOverlay } from '@/components/annotation/ShuttleTrackOverlay'
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
}: Props) {
  return (
    <div ref={videoContainerRef} className="relative w-full">
      <VideoPlayer
        videoRefProp={videoRef}
        src={src}
        playbackRate={playbackRate}
        onPlaybackRateChange={onPlaybackRateChange}
      />
      {yoloFrames.length > 0 && videoContainerRef.current && (
        <PlayerPositionOverlay
          frames={yoloFrames}
          currentSec={currentVideoSec}
          videoWidth={videoContainerRef.current.clientWidth}
          videoHeight={videoContainerRef.current.clientHeight}
          visible={yoloOverlayVisible}
        />
      )}
      {shuttleFrames.length > 0 && videoContainerRef.current && (
        <ShuttleTrackOverlay
          frames={shuttleFrames}
          currentSec={currentVideoSec}
          videoWidth={videoContainerRef.current.clientWidth}
          videoHeight={videoContainerRef.current.clientHeight}
          visible={shuttleOverlayVisible}
        />
      )}
    </div>
  )
}
