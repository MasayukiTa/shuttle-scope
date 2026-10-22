import { apiGetBlob } from '@/api/client'
import { saveBlobAs } from '@/utils/saveBlob'

export type ExpertExportResult = 'ok' | 'denied' | 'failed'

/**
 * Expert Labeler の JSON / CSV を Bearer 付きで取得して保存する。
 * 生の `<a href>` は Authorization を付けられず 401 になるため apiGetBlob を通す。
 * 失敗は例外にせず結果コードで返し、呼び出し側が画面内に表示する。
 */
export async function downloadExpertExport(
  path: string,
  params: Record<string, string | number>,
  fallbackName: string,
): Promise<ExpertExportResult> {
  try {
    const { blob, filename } = await apiGetBlob(path, params)
    saveBlobAs(blob, filename ?? fallbackName)
    return 'ok'
  } catch (e) {
    const status = (e as { status?: number } | null)?.status
    return status === 401 || status === 403 ? 'denied' : 'failed'
  }
}
