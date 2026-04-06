/**
 * VideoOnlyPage — 別モニタ用フルスクリーン動画表示
 * Electron の openVideoWindow IPC で開かれる独立ウィンドウ向けページ。
 * サイドバーなし・ナビなし・動画のみ。
 */
import { useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { VideoPlayer } from '@/components/video/VideoPlayer'
import { WebViewPlayer } from '@/components/video/WebViewPlayer'
import { useVideo } from '@/hooks/useVideo'

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

export function VideoOnlyPage() {
  const [searchParams] = useSearchParams()
  const src = searchParams.get('src') ?? ''
  const videoRef = useRef<HTMLVideoElement>(null)
  const { playbackRate, setPlaybackRate } = useVideo(videoRef)

  if (!src) {
    return (
      <div className="flex items-center justify-center w-screen h-screen bg-black text-gray-500 text-sm">
        動画ソースが指定されていません
      </div>
    )
  }

  return (
    <div className="w-screen h-screen bg-black overflow-hidden">
      {isStreamingUrl(src) ? (
        <WebViewPlayer url={src} siteName="動画" />
      ) : (
        <VideoPlayer
          videoRefProp={videoRef}
          src={src}
          playbackRate={playbackRate}
          onPlaybackRateChange={setPlaybackRate}
        />
      )}
    </div>
  )
}
