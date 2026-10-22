import type { AuditLogSourceSummary } from '@/api/client'

export type AuditEmptyReason = 'unknown' | 'never_recorded' | 'filtered'

/**
 * 一覧が 0 件のときの理由。
 * 状態を取得できていない: unknown / 表そのものが空: never_recorded / 表には記録があるが絞り込みに合わない: filtered
 */
export function auditEmptyReason(summary: AuditLogSourceSummary | null | undefined): AuditEmptyReason {
  if (!summary) return 'unknown'
  return summary.total > 0 ? 'filtered' : 'never_recorded'
}
