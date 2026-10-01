import { API_BASE_URL } from '@/api/client'

/**
 * 試合の動画再生 URL を生成する。
 *
 * 優先順位:
 *   1. ブラウザ + サーバ保管動画 → /api/v1/uploads/video/by_match/{id}/stream?token=...
 *      (Range 対応 206 で <video> が seek 可能、video_token クエリ認証)
 *   2. Electron + video_token → app://video/{token} (内部 protocol)
 *   3. video_url (YouTube などの外部 URL)
 *   4. 空文字
 */
function _isElectron(): boolean {
  if (typeof navigator === 'undefined') return false
  return navigator.userAgent.toLowerCase().includes('electron')
}

export function getVideoSrc(match?: {
  id?: number
  video_token?: string | null
  video_url?: string | null
  has_video_local?: boolean | null
} | null): string {
  if (!match) return ''

  const inElectron = _isElectron()

  // ブラウザ環境でサーバ保管動画がある場合は HTTP stream を使う
  // (app:// は Electron 専用 protocol でブラウザでは再生不能)
  if (!inElectron && match.has_video_local && match.id && match.video_token) {
    return `/api/v1/uploads/video/by_match/${match.id}/stream?token=${encodeURIComponent(match.video_token)}`
  }

  if (inElectron && match.video_token) {
    return `app://video/${match.video_token}`
  }

  if (match.video_url) return match.video_url
  return ''
}


/**
 * モバイルアノテ専用: video_token + match.id があれば即 stream URL を返す。
 *
 * `/api/videos/{token}/stream` は Bearer JWT を要求するため <video> タグから
 * 直接読めない。代わりに `/api/v1/uploads/video/by_match/{id}/stream?token=...`
 * を使う。これは `<video>` タグ用に query token 認証経路を持っていて、
 * Range header にも対応している。
 *
 * has_video_local が False でも token があれば試行する (= サーバに動画ファイル
 * があれば再生、無ければ <video onError> で 404 を可視化)。
 */
export type MobileVideoQuality = 'source' | 'play' | 'uhd' | 'fhd' | 'hd'

export type MobileQualityOption = {
  quality: MobileVideoQuality
  height: number
  ready: boolean
}

export function chooseMobileVideoQuality(
  options: MobileQualityOption[],
  requested: MobileVideoQuality,
): MobileVideoQuality {
  const requestedOption = options.find((q) => q.quality === requested)
  if (requestedOption?.ready) return requested

  const play = options.find((q) => q.quality === 'play' && q.ready)
  if (play) return 'play'

  const readyVariant = options.find((q) => q.quality !== 'source' && q.ready)
  if (readyVariant) return readyVariant.quality

  const source = options.find((q) => q.quality === 'source' && q.ready)
  return source?.quality ?? 'source'
}


export function getMobileVideoSrc(
  match?: {
    id?: number
    video_token?: string | null
    video_url?: string | null
    has_video_local?: boolean | null
  } | null,
  quality?: MobileVideoQuality | null,
): string {
  if (!match) return ''
  if (match.id && match.video_token) {
    const base = `/api/v1/uploads/video/by_match/${match.id}/stream?token=${encodeURIComponent(match.video_token)}`
    // undefined/null = backend auto selection. Once the UI names a quality,
    // including "source", encode it explicitly so the chip label matches
    // the bytes served.
    if (quality) {
      return `${base}&quality=${encodeURIComponent(quality)}`
    }
    return base
  }
  if (match.video_url) return match.video_url
  return ''
}


/**
 * 動画が登録されているかを判定する。
 */
export function hasVideo(match?: {
  video_token?: string | null
  video_url?: string | null
  has_video_local?: boolean | null
} | null): boolean {
  if (!match) return false
  return !!(match.video_token || match.video_url || match.has_video_local)
}

/**
 * 表示用のファイル名（パスを含まない）。video_filename 優先。
 */
export function getVideoLabel(match?: {
  video_filename?: string | null
  video_url?: string | null
  has_video_local?: boolean | null
} | null): string {
  if (!match) return ''
  if (match.video_filename) return `📁 ${match.video_filename}`
  if (match.video_url) return `🔗 ${match.video_url}`
  if (match.has_video_local) return '📁 (動画登録済み)'
  return ''
}

export type RecordingVideoRef = {
  id?: number
  video_token?: string | null
}

/**
 * Recording branch のブラウザ再生 URL。
 *
 * Match.video_token と同様に raw filesystem path はクライアントへ渡さず、
 * branch 固有 token で Range 対応 stream endpoint を参照する。
 */
export function getRecordingVideoSrc(recording?: RecordingVideoRef | null): string {
  if (!recording?.id || !recording.video_token) return ''
  return `${API_BASE_URL}/recordings/${recording.id}/stream?token=${encodeURIComponent(recording.video_token)}`
}
