import { useRef, useState, useEffect, useCallback, RefObject } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Play, Pause, SkipBack, SkipForward,
  ChevronLeft, ChevronRight, AlertTriangle
} from 'lucide-react'
import { clsx } from 'clsx'

interface VideoPlayerProps {
  src: string
  playbackRate: number
  onPlaybackRateChange: (rate: number) => void
  /** 親から渡す ref — useKeyboard でのシーク操作・再生制御に使用 */
  videoRefProp?: RefObject<HTMLVideoElement>
}

const PLAYBACK_RATES = [0.25, 0.5, 1, 2] as const
const FRAME_DURATION = 1 / 30

function isYouTubeUrl(url: string): boolean {
  return url.includes('youtube.com') || url.includes('youtu.be')
}

function getYouTubeEmbedUrl(url: string): string {
  const match = url.match(/(?:v=|youtu\.be\/|shorts\/)([a-zA-Z0-9_-]{11})/)
  // youtube-nocookie.com は Electron での iframe 制限が少ない
  if (match) return `https://www.youtube-nocookie.com/embed/${match[1]}?rel=0&modestbranding=1`
  return url
}

/**
 * 動画プレイヤーコンポーネント
 * - videoRefProp: 親の useRef を接続して useKeyboard からシーク・再生制御可能にする
 * - Space キーのブラウザデフォルト動作を preventDefault — useKeyboard 側で一元管理
 */
export function VideoPlayer({
  src,
  playbackRate,
  onPlaybackRateChange,
  videoRefProp,
}: VideoPlayerProps) {
  const { t } = useTranslation()
  const internalRef = useRef<HTMLVideoElement>(null)
  const videoRef = videoRefProp ?? internalRef

  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [isYouTube, setIsYouTube] = useState(false)

  useEffect(() => {
    setIsYouTube(isYouTubeUrl(src))
  }, [src])

  useEffect(() => {
    if (videoRef.current) videoRef.current.playbackRate = playbackRate
  }, [playbackRate, videoRef])

  const togglePlay = useCallback(() => {
    if (!videoRef.current) return
    if (isPlaying) {
      videoRef.current.pause()
    } else {
      videoRef.current.play()
    }
  }, [isPlaying, videoRef])

  const stepForward = useCallback(() => {
    if (!videoRef.current || isYouTube) return
    videoRef.current.pause()
    videoRef.current.currentTime = Math.min(videoRef.current.currentTime + FRAME_DURATION, duration)
  }, [isYouTube, duration, videoRef])

  const stepBackward = useCallback(() => {
    if (!videoRef.current || isYouTube) return
    videoRef.current.pause()
    videoRef.current.currentTime = Math.max(videoRef.current.currentTime - FRAME_DURATION, 0)
  }, [isYouTube, videoRef])

  const seekForward = useCallback(() => {
    if (!videoRef.current) return
    videoRef.current.currentTime = Math.min(videoRef.current.currentTime + 10, duration)
  }, [duration, videoRef])

  const seekBackward = useCallback(() => {
    if (!videoRef.current) return
    videoRef.current.currentTime = Math.max(videoRef.current.currentTime - 10, 0)
  }, [videoRef])

  const handleSeek = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (!videoRef.current || !duration) return
      const rect = e.currentTarget.getBoundingClientRect()
      const ratio = (e.clientX - rect.left) / rect.width
      videoRef.current.currentTime = ratio * duration
    },
    [duration, videoRef]
  )

  const formatTime = (sec: number) => {
    const m = Math.floor(sec / 60)
    const s = Math.floor(sec % 60)
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  }

  if (isYouTube) {
    return (
      <div className="flex flex-col gap-2">
        <div className="relative w-full" style={{ paddingTop: '56.25%' }}>
          <iframe
            src={getYouTubeEmbedUrl(src)}
            className="absolute inset-0 w-full h-full rounded"
            allowFullScreen
            title="YouTube Video"
          />
        </div>
        <div className="flex items-center gap-2 p-2 bg-yellow-900/30 border border-yellow-600/50 rounded text-yellow-300 text-xs">
          <AlertTriangle size={14} />
          <span>{t('video.youtube_warning')}</span>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-2">
      {/* 動画本体 */}
      <div className="relative w-full bg-black rounded overflow-hidden" style={{ aspectRatio: '16/9' }}>
        <video
          ref={videoRef}
          src={src}
          className="w-full h-full object-contain"
          onTimeUpdate={() => setCurrentTime(videoRef.current?.currentTime ?? 0)}
          onLoadedMetadata={() => setDuration(videoRef.current?.duration ?? 0)}
          onPlay={() => setIsPlaying(true)}
          onPause={() => setIsPlaying(false)}
          onEnded={() => setIsPlaying(false)}
          // Space のブラウザデフォルト再生/停止を無効化 — useKeyboard で一元管理
          onKeyDown={(e) => { if (e.key === ' ') e.preventDefault() }}
        />
      </div>

      {/* シークバー */}
      <div
        className="h-2 bg-gray-700 rounded-full cursor-pointer hover:bg-gray-600 transition-colors"
        onClick={handleSeek}
      >
        <div
          className="h-full bg-blue-500 rounded-full transition-all"
          style={{ width: `${duration ? (currentTime / duration) * 100 : 0}%` }}
        />
      </div>

      {/* タイム表示 */}
      <div className="text-xs text-gray-400 text-center font-mono">
        {formatTime(currentTime)} / {formatTime(duration)}
      </div>

      {/* コントロールバー */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1">
          <button onClick={seekBackward} className="p-1 rounded hover:bg-gray-700 text-gray-300" title="10秒戻し (Shift+←)">
            <SkipBack size={16} />
          </button>
          <button onClick={stepBackward} className="p-1 rounded hover:bg-gray-700 text-gray-300" title="1フレーム戻し (←)">
            <ChevronLeft size={16} />
          </button>
          <button
            onClick={togglePlay}
            className="p-2 rounded bg-blue-600 hover:bg-blue-500 text-white"
            title={isPlaying ? '一時停止 (Space)' : '再生 (Space)'}
          >
            {isPlaying ? <Pause size={18} /> : <Play size={18} />}
          </button>
          <button onClick={stepForward} className="p-1 rounded hover:bg-gray-700 text-gray-300" title="1フレーム進め (→)">
            <ChevronRight size={16} />
          </button>
          <button onClick={seekForward} className="p-1 rounded hover:bg-gray-700 text-gray-300" title="10秒進め (Shift+→)">
            <SkipForward size={16} />
          </button>
        </div>

        {/* 再生速度 */}
        <div className="flex items-center gap-1">
          {PLAYBACK_RATES.map((rate) => (
            <button
              key={rate}
              onClick={() => onPlaybackRateChange(rate)}
              className={clsx(
                'px-2 py-1 rounded text-xs font-mono',
                playbackRate === rate
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
              )}
            >
              {rate}x
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
