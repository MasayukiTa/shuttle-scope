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
