/**
 * 試合の動画再生 URL を生成する。
 *
 * Phase 1 セキュリティ要件:
 *   - 生のローカルパス (video_local_path) はバックエンドが API レスポンスに含めない
 *   - フロントは video_token のみを受け取り、app://video/{token} でアクセスする
 *   - app:// は Electron が登録するプロトコルでバックエンドの
 *     /api/videos/{token}/stream へプロキシされる
 *
 * 優先順位:
 *   1. video_token (ローカル動画) → app://video/{token}
 *   2. video_url (YouTube などの外部 URL)
 *   3. 空文字（動画未登録）
 */
export function getVideoSrc(match?: {
  video_token?: string | null
  video_url?: string | null
  has_video_local?: boolean | null
} | null): string {
  if (!match) return ''
  if (match.video_token) return `app://video/${match.video_token}`
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
