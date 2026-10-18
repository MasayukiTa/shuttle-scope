/**
 * 承認待ちユーザ数 (admin 専用)。
 *
 * 新規登録の通知は管理画面内でしか確認できないため、ナビのバッジ用に件数だけを
 * 60 秒間隔で取得する。
 * - admin 以外のロールでは query 自体を無効化し、リクエストを一切送らない。
 * - タブが非表示の間は polling しない (refetchIntervalInBackground=false)。
 * - 401/403 を受けたら polling を止める。
 * - 取得に失敗した間は null を返す (偽の 0 は返さない)。
 */
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'

export const PENDING_APPROVAL_POLL_MS = 60_000

interface PendingListResp {
  success: boolean
  data: unknown[]
}

function isAuthError(err: unknown): boolean {
  const status = (err as { status?: number } | null)?.status
  return status === 401 || status === 403
}

export function usePendingApprovalCount(role: string | null | undefined): number | null {
  const isAdmin = role === 'admin'
  const query = useQuery({
    queryKey: ['pending-approvals-count'],
    queryFn: () => apiGet<PendingListResp>('/auth/users/pending'),
    enabled: isAdmin,
    retry: false,
    refetchInterval: (q) => (isAuthError(q.state.error) ? false : PENDING_APPROVAL_POLL_MS),
    refetchIntervalInBackground: false,
  })
  if (!isAdmin || query.isError) return null
  const rows = query.data?.data
  return Array.isArray(rows) ? rows.length : null
}
