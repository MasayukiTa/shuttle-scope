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

/** ローカル暦で months か月前の同じ日。存在しない日 (3/31 の 1 か月前など) は Date の繰り上げに従う。 */
export function localDateMonthsAgo(months: number, now: Date = new Date()): string {
  return formatLocalDate(new Date(now.getFullYear(), now.getMonth() - months, now.getDate()))
}

/** ローカル暦で years 年前の同じ日。 */
export function localDateYearsAgo(years: number, now: Date = new Date()): string {
  return formatLocalDate(new Date(now.getFullYear() - years, now.getMonth(), now.getDate()))
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
