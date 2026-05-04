import { useState, useCallback, RefObject } from 'react'

/**
 * 動画制御フック
 */
export function useVideo(videoRef: RefObject<HTMLVideoElement>) {
  const [playbackRate, setPlaybackRateState] = useState(1)
  const [isPlaying, setIsPlaying] = useState(false)

  const setPlaybackRate = useCallback((rate: number) => {
    setPlaybackRateState(rate)
    if (videoRef.current) {
      videoRef.current.playbackRate = rate
    }
  }, [videoRef])

  const getCurrentTime = useCallback((): number => {
    return videoRef.current?.currentTime ?? 0
  }, [videoRef])

  return { playbackRate, setPlaybackRate, isPlaying, setIsPlaying, getCurrentTime }
}
