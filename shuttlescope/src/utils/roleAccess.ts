import type { UserRole } from '@/types'

/**
 * Condition 画面は選手本人の入力と、運用ロール (admin/analyst/coach) の閲覧を前提にする。
 * demo は read-only の見本用ロールで、本人入力も選手の切替閲覧も成立しないため、
 * 導線とルートの両方で除外する。ロール未確定 (null/undefined) は従来どおり扱う。
 */
export function canUseConditionPage(role: UserRole | null | undefined): boolean {
  return role !== 'demo'
}

/** ロール未確定 (null/undefined) は従来どおり表示側で扱う (サーバが最終判定する)。 */
type RoleArg = UserRole | null | undefined

/**
 * 試合の登録 / クイックスタート / 編集の導線を出してよいか。
 * backend の POST /matches・PUT /matches/{id}・POST /matches/quick-start は
 * admin / coach / analyst だけを許可する (player は 403、demo は
 * resolve_owner_team_for_match_create と user_can_access_match が拒否)。
 */
export function canWriteMatch(role: RoleArg): boolean {
  if (role == null) return true
  return role === 'admin' || role === 'coach' || role === 'analyst'
}

/** 試合削除の導線を出してよいか。backend の DELETE /matches/{id} は admin / analyst のみ (coach は 403)。 */
export function canDeleteMatch(role: RoleArg): boolean {
  if (role == null) return true
  return role === 'admin' || role === 'analyst'
}

/** 選手削除の導線を出してよいか。backend の DELETE /players/{id} は require_analyst (analyst / admin のみ。coach は 403)。 */
export function canDeletePlayer(role: RoleArg): boolean {
  if (role == null) return true
  return role === 'admin' || role === 'analyst'
}

/** 解析ジョブ状態の閲覧可否。backend の GET /v1/pipeline/jobs は analyst / coach 以外へ常に空配列を返すため、それ以外へ「未解析」を出さない。 */
export function canViewPipelineJobs(role: RoleArg): boolean {
  if (role == null) return true
  return role === 'analyst' || role === 'coach'
}
