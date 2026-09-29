import { useRef, useState, useEffect, useCallback, RefObject, type ReactNode } from 'react'
import { clsx } from 'clsx'
import { useTranslation } from 'react-i18next'
import { MIcon } from '@/components/common/MIcon'

interface VideoPlayerProps {
  src: string
  playbackRate: number
  onPlaybackRateChange: (rate: number) => void
  /** 親から渡す ref — useKeyboard でのシーク操作・再生制御に使用 */
  videoRefProp?: RefObject<HTMLVideoElement>
  /** ビデオエリア div（aspect-ratio ボックス）への ref — オーバーレイ配置用 */
  videoAreaRef?: RefObject<HTMLDivElement>
  /** ビデオエリア内に描画するオーバーレイ群（absolute inset-0 想定） */
  overlays?: ReactNode
}

const PLAYBACK_RATES = [0.25, 0.5, 1, 2] as const
const FRAME_DURATION = 1 / 30

/**
 * ローカル動画プレイヤーコンポーネント
 * localfile:// URL または直接再生可能な URL を受け付ける。
 * 配信URL（YouTube 等）は AnnotatorPage 側の StreamingDownloadPanel で処理する。
 */
export function VideoPlayer({
  src,
  playbackRate,
  onPlaybackRateChange,
  videoRefProp,
  videoAreaRef,
  overlays,
}: VideoPlayerProps) {
  const { t } = useTranslation()

  const internalRef = useRef<HTMLVideoElement>(null)
  const videoRef = videoRefProp ?? internalRef

  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  // シークバーホバー時のツールチップ
  const [seekHover, setSeekHover] = useState<{ x: number; pct: number } | null>(null)

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
    if (!videoRef.current) return
    videoRef.current.pause()
    videoRef.current.currentTime = Math.min(videoRef.current.currentTime + FRAME_DURATION, duration)
  }, [duration, videoRef])

  const stepBackward = useCallback(() => {
    if (!videoRef.current) return
    videoRef.current.pause()
    videoRef.current.currentTime = Math.max(videoRef.current.currentTime - FRAME_DURATION, 0)
  }, [videoRef])

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

  return (
    <div className="flex flex-col gap-2">
      {/* 動画本体 — オーバーレイはこの div 内に配置（コントロールに被らない） */}
      <div
        ref={videoAreaRef}
        className="relative w-full bg-black rounded overflow-hidden"
        style={{ aspectRatio: '16/9' }}
      >
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
        {overlays}
      </div>

      {/* シークバー（ホバーで時刻ツールチップ表示） */}
      <div className="relative">
        {seekHover && duration > 0 && (
          <div
            className="absolute bottom-full mb-1.5 -translate-x-1/2 bg-[var(--ss-surface-1)] text-[var(--ss-t1)] text-xs rounded-[5px] px-1.5 py-0.5 pointer-events-none whitespace-nowrap shadow-lg z-10 border border-[var(--ss-border)]"
            style={{ left: seekHover.x }}
          >
            {formatTime(seekHover.pct * duration)}
          </div>
        )}
        <div
          className="h-2 bg-[var(--ss-surface-2)] rounded-full cursor-pointer hover:bg-[var(--ss-surface-3)] transition-colors"
          onClick={handleSeek}
          onMouseMove={(e) => {
            const rect = e.currentTarget.getBoundingClientRect()
            const x = e.clientX - rect.left
            const pct = Math.max(0, Math.min(1, x / rect.width))
            setSeekHover({ x, pct })
          }}
          onMouseLeave={() => setSeekHover(null)}
        >
          <div
            className="h-full bg-[var(--ss-brand)] rounded-full transition-all"
            style={{ width: `${duration ? (currentTime / duration) * 100 : 0}%` }}
          />
        </div>
      </div>

      {/* タイム表示 */}
      <div className="text-xs text-[var(--ss-t3)] text-center font-mono ss-num">
        {formatTime(currentTime)} / {formatTime(duration)}
      </div>

      {/* コントロールバー */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1">
          <button onClick={seekBackward} className="p-1 rounded-[5px] hover:bg-[var(--ss-surface-2)] text-[var(--ss-t2)]" title={t('auto.VideoPlayer.k1')}>
            <MIcon name="skip_previous" size={16} />
          </button>
          <button onClick={stepBackward} className="p-1 rounded-[5px] hover:bg-[var(--ss-surface-2)] text-[var(--ss-t2)]" title={t('auto.VideoPlayer.k2')}>
            <MIcon name="chevron_left" size={16} />
          </button>
          <button
            onClick={togglePlay}
            className="p-2 rounded-[5px] bg-[var(--ss-brand)] hover:bg-[var(--ss-brand-hover)] text-white"
            title={isPlaying ? t('auto.VideoPlayer.pause') : t('auto.VideoPlayer.play')}
          >
            {isPlaying ? <MIcon name="pause" size={18} /> : <MIcon name="play_arrow" size={18} />}
          </button>
          <button onClick={stepForward} className="p-1 rounded-[5px] hover:bg-[var(--ss-surface-2)] text-[var(--ss-t2)]" title={t('auto.VideoPlayer.k3')}>
            <MIcon name="chevron_right" size={16} />
          </button>
          <button onClick={seekForward} className="p-1 rounded-[5px] hover:bg-[var(--ss-surface-2)] text-[var(--ss-t2)]" title={t('auto.VideoPlayer.k4')}>
            <MIcon name="skip_next" size={16} />
          </button>
        </div>

        {/* 再生速度 */}
        <div className="flex items-center gap-1">
          {PLAYBACK_RATES.map((rate) => (
            <button
              key={rate}
              onClick={() => onPlaybackRateChange(rate)}
              className={clsx(
                'px-2 py-1 rounded-[5px] text-xs font-mono ss-num',
                playbackRate === rate
                  ? 'bg-[var(--ss-brand)] text-white'
                  : 'bg-[var(--ss-surface-2)] text-[var(--ss-t2)] hover:bg-[var(--ss-surface-3)]'
              )}
            >
              {t('auto.VideoPlayer.speed', { rate })}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
