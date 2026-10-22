/**
 * 回答妥当性の要約に、表示できる中身があるか。
 * 比率 (valid_ratio) もフラグも無いとき、ラベルだけが出ないように呼び出し側で隠す。
 * 比率が 0 の場合は「妥当な回答が 0%」という値なので、表示対象。
 */
export function hasValiditySummary(
  v: { valid_ratio?: number | null; flags?: string[] | null } | null | undefined,
): boolean {
  if (!v) return false
  if (v.valid_ratio != null) return true
  return Array.isArray(v.flags) && v.flags.length > 0
}
