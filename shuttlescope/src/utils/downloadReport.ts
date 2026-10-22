// PDF / JSON レポートのダウンロード共通ヘルパー。
// 以前は各画面が fetch の結果を ok / Content-Type の確認なしに blob 化して保存しており、
// 401 / 403 / 500 のエラー本文が report_player*.pdf 等の正常なファイル名で保存されていた。
import { apiGetReportBlob } from '@/api/client'

/** 期待した種類のファイルではない応答 (HTTP 200 でも JSON/HTML のエラー本文など) */
export class ReportContentTypeError extends Error {
  constructor(filename: string, received: string) {
    super(`Unexpected content type for ${filename}: ${received || '(none)'}`)
    this.name = 'ReportContentTypeError'
  }
}

/** ファイル名の拡張子から期待する Content-Type かを判定する */
export function isExpectedReportType(filename: string, mime: string): boolean {
  const type = (mime.split(';')[0] ?? '').trim().toLowerCase()
  const name = filename.toLowerCase()
  if (name.endsWith('.pdf')) {
    return type === 'application/pdf' || type === 'application/octet-stream'
  }
  if (name.endsWith('.json')) {
    return type === 'application/json' || type.endsWith('+json')
  }
  return true
}

/**
 * レポートを取得して保存する。HTTP 失敗・種類違いの応答は例外にし、ファイルは保存しない。
 * path は従来どおり `/api/...` 始まりでも `/...` 始まりでもよい。
 */
export async function downloadReport(path: string, filename: string): Promise<void> {
  const blob = await apiGetReportBlob(path.replace(/^\/api/, ''))
  if (!isExpectedReportType(filename, blob.type)) {
    throw new ReportContentTypeError(filename, blob.type)
  }
  const url = URL.createObjectURL(blob)
  try {
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
  } finally {
    URL.revokeObjectURL(url)
  }
}
