/**
 * 管理画面のユーザ削除ボタンを出してよいかの判定。
 *
 * backend の DELETE /auth/users/{id} (routers/auth.py delete_user) と同じ規則:
 *   1. 自分自身は削除できない (400 cannot delete your own user)
 *   2. 検証用 (is_test) でも承認待ち (awaiting_admin_approval) でもない承認済みの実ユーザは、
 *      force 指定なしでは 403 で拒否される。UI は force を送らないため、ボタン自体を出さない。
 */
export interface DeletableUserRow {
  id: number
  is_test?: boolean
  awaiting_admin_approval?: boolean
}

export function canShowDeleteButton(
  row: DeletableUserRow,
  myUserId: number | null | undefined,
  isAdmin: boolean,
): boolean {
  if (!isAdmin) return false
  if (myUserId != null && row.id === myUserId) return false
  const isProtected = !row.is_test && !row.awaiting_admin_approval
  return !isProtected
}
