// MatchListPage から共有する純粋ヘルパ (god-file 分割フェーズ1, 2026-05-21)。

// アノテーション進捗ステータスごとの文字色 (mobile card / desktop table 共用)
export function statusColor(status: string): string {
  switch (status) {
    case 'complete': return 'text-green-400'
    case 'in_progress': return 'text-yellow-400'
    case 'reviewed': return 'text-blue-400'
    default: return 'text-gray-400'
  }
}

// 動画ダウンロード進捗エントリ (dlByMatch[String(matchId)] の型)
export interface DownloadStatus {
  status: string
  percent?: string
  eta?: string
  error?: string
}
