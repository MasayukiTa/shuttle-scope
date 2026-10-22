import type { UserRole } from '@/types'

/**
 * Condition 画面は選手本人の入力と、運用ロール (admin/analyst/coach) の閲覧を前提にする。
 * demo は read-only の見本用ロールで、本人入力も選手の切替閲覧も成立しないため、
 * 導線とルートの両方で除外する。ロール未確定 (null/undefined) は従来どおり扱う。
 */
export function canUseConditionPage(role: UserRole | null | undefined): boolean {
  return role !== 'demo'
}
