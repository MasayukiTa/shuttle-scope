// 数値表示の共有ヘルパー。
// バックエンドは 0 件の集計で null / 欠落 / NaN を返すことがあり、`(v * 100).toFixed(1)` を
// そのまま使うと画面に "NaN%" が出る (B-43)。割合の文字列化はここ 1 か所に集約し、
// 非有限値は「計測不能」を意味する "—" にする。

/** 0〜1 の割合を "12.3%" にする。null / undefined / NaN / Infinity は "—"。 */
export function fmtPct(v: number | null | undefined, digits = 1): string {
  if (typeof v !== 'number' || !Number.isFinite(v)) return '—'
  return `${(v * 100).toFixed(digits)}%`
}

/** 有限な数値か (チャート・差分の描画可否判定用)。 */
export function isFiniteNumber(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v)
}
