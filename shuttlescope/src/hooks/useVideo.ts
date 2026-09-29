import { useState, useCallback, useEffect, RefObject } from 'react'

/**
 * 動画制御フック
 */
export function useVideo(videoRef: RefObject<HTMLVideoElement>) {
  const [playbackRate, setPlaybackRateState] = useState(1)
  const [isPlaying, setIsPlaying] = useState(false)

  // isPlaying を実際の再生状態に同期する (旧版は state を宣言するだけで video の
  // play/pause イベントに繋いでおらず、常に false の dead state だった)。
  useEffect(() => {
    const v = videoRef.current
    if (!v) return
    const onPlay = () => setIsPlaying(true)
    const onPause = () => setIsPlaying(false)
    v.addEventListener('play', onPlay)
    v.addEventListener('pause', onPause)
    v.addEventListener('ended', onPause)
    setIsPlaying(!v.paused)
    return () => {
      v.removeEventListener('play', onPlay)
      v.removeEventListener('pause', onPause)
      v.removeEventListener('ended', onPause)
    }
  }, [videoRef])

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
