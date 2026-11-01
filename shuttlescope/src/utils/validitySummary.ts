/**
 * 回答妥当性の要約に、表示できる中身があるか。
 * backend は { counts: { ok, caution, unreliable }, n } を返す (監査#750)。
 * n が 0 のときは集計対象が無いのでラベルごと隠す。
 */
export interface ValiditySummary {
  counts?: { ok: number; caution: number; unreliable: number } | null
  n?: number | null
}

export function hasValiditySummary(
  v: ValiditySummary | null | undefined,
): boolean {
  if (!v) return false
  if (v.n != null && v.n > 0) return true
  const c = v.counts
  if (!c) return false
  return (c.ok ?? 0) + (c.caution ?? 0) + (c.unreliable ?? 0) > 0
}
