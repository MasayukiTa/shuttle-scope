/**
 * 日付だけの値 (YYYY-MM-DD) をローカル暦から作るヘルパー。
 *
 * 防ぐ事象 (監査 #796): `new Date().toISOString().split('T')[0]` は UTC の日付を返すため、
 * 日本時間の 0:00〜8:59 は前日になり、分析期間の「今日」「1ヶ月前」が 1 日ずれていた。
 * 業務日付はタイムゾーンを経由せず、ローカルの年・月・日から組み立てる。
 */

function pad2(n: number): string {
  return n < 10 ? `0${n}` : String(n)
}

/** ローカル暦の年月日を YYYY-MM-DD にする。 */
export function formatLocalDate(d: Date): string {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`
}

/** ローカル暦の今日。 */
export function todayLocal(now: Date = new Date()): string {
  return formatLocalDate(now)
}

/** ローカル暦で days 日前 (負数なら後) の日付。 */
export function localDateDaysAgo(days: number, now: Date = new Date()): string {
  return formatLocalDate(new Date(now.getFullYear(), now.getMonth(), now.getDate() - days))
}

/**
 * ローカル暦で months か月前の同じ日。移動先の月にその日が無いとき (3/31 の 1 か月前など) は
 * 移動先の月末へ丸める。`new Date(y, m - n, d)` のままだと翌月へ繰り上がり、
 * 期間が数日短くなって分析の母集団がずれる (監査 #952)。
 */
export function localDateMonthsAgo(months: number, now: Date = new Date()): string {
  const first = new Date(now.getFullYear(), now.getMonth() - months, 1)
  const lastDay = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate()
  return formatLocalDate(new Date(first.getFullYear(), first.getMonth(), Math.min(now.getDate(), lastDay)))
}

/** ローカル暦で years 年前の同じ日。うるう日 (2/29) の 1 年前は 2/28 に丸める。 */
export function localDateYearsAgo(years: number, now: Date = new Date()): string {
  return localDateMonthsAgo(years * 12, now)
}

export type RangePreset = '1m' | '3m' | '6m' | '1y' | 'all'

/** 期間プリセットの開始日 (ローカル暦)。'all' は空文字 (= 下限なし)。 */
export function presetFromDate(preset: RangePreset, now: Date = new Date()): string {
  switch (preset) {
    case 'all': return ''
    case '1m': return localDateMonthsAgo(1, now)
    case '3m': return localDateMonthsAgo(3, now)
    case '6m': return localDateMonthsAgo(6, now)
    case '1y': return localDateYearsAgo(1, now)
  }
}

/** 開始日 > 終了日か。どちらかが空なら逆転ではない (YYYY-MM-DD は辞書順 = 日付順)。 */
export function isReversedRange(from: string | null | undefined, to: string | null | undefined): boolean {
  return Boolean(from && to && from > to)
}
