/**
 * VideoOnlyPage — 別モニタ用フルスクリーン動画表示
 * Electron の openVideoWindow IPC で開かれる独立ウィンドウ向けページ。
 * - サイドバー・ナビなし、動画のみ全画面
 * - src + t（開始秒）を URL パラメータで受け取り、その位置から自動再生
 */
import { useRef, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { WebViewPlayer } from '@/components/video/WebViewPlayer'

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
  const startTime = parseFloat(searchParams.get('t') ?? '0')
  // メインウィンドウで一時停止中だった場合は別モニタでも停止状態を維持
  const startPaused = searchParams.get('paused') === '1'
  const videoRef = useRef<HTMLVideoElement>(null)

  // 動画ロード後に開始位置へシーク、停止中でなければ再生
  useEffect(() => {
    const video = videoRef.current
    if (!video) return

    const onLoaded = () => {
      if (startTime > 0) {
        video.currentTime = startTime
      }
      if (!startPaused) {
        video.play().catch(() => {
          // autoplay 失敗は無視（Electron では通常許可される）
        })
      }
    }

    video.addEventListener('loadedmetadata', onLoaded)
    return () => video.removeEventListener('loadedmetadata', onLoaded)
  }, [src, startTime, startPaused])

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

  return (
    <div className="w-screen h-screen bg-black overflow-hidden flex items-center justify-center">
      <video
        ref={videoRef}
        src={src}
        className="w-full h-full object-contain"
        // controls を表示（別モニタでも操作できるように）
        controls
        playsInline
      />
    </div>
  )
}
