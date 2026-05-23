/**
 * parsePeriod — 日本語/英語の自由入力から日付範囲 (dateFrom, dateTo) を抽出する
 * ルールベース (非 LLM) のピュア関数。
 *
 * Growth Advisor チャット入力欄で 「25/03から今まで」「先月の」「直近3ヶ月で」
 * のような表現を検出し、確認チップ UI で範囲を見せるために使う。
 *
 * 設計方針:
 *   - 依存ゼロ (date-fns を入れない: package.json に未導入のため native Date のみ)
 *   - ピュア関数: now を引数で受けて単体テスト可能にする
 *   - 出力は 'YYYY-MM-DD' の ISO 文字列 (UTC ではなくローカル暦で日付を切り出す)
 *   - 優先度順 (上から走査し最初にマッチしたものを返す):
 *       1. 絶対範囲 (YYYY/M/D 〜 YYYY/M/D, ISO 〜 ISO)
 *       2. 絶対開始 + open-end (YYYY/M/D から 今まで / 現在まで)
 *       3. 単一月/年指定 (2025年3月, 今月, 先月, 今年, 去年)
 *       4. 相対 duration (直近 N 日/週/ヶ月/年, past N days/weeks/months)
 *       5. today/yesterday/this week/last week
 *       6. 何も拾えなければ confidence='none'
 */

export type PeriodConfidence = 'exact' | 'heuristic' | 'none'

export interface ParsedPeriod {
  dateFrom: string | null
  dateTo: string | null
  label: string
  confidence: PeriodConfidence
  matchedText: string
}

// ─────────────────────────────────────────────────────────────
// helpers
// ─────────────────────────────────────────────────────────────

function pad2(n: number): string {
  return n < 10 ? `0${n}` : String(n)
}

function fmt(d: Date): string {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`
}

function startOfDay(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate())
}

function startOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), 1)
}

function endOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth() + 1, 0)
}

function addDays(d: Date, n: number): Date {
  const r = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  r.setDate(r.getDate() + n)
  return r
}

function addMonths(d: Date, n: number): Date {
  return new Date(d.getFullYear(), d.getMonth() + n, d.getDate())
}

function addYears(d: Date, n: number): Date {
  return new Date(d.getFullYear() + n, d.getMonth(), d.getDate())
}

function startOfWeek(d: Date): Date {
  // 月曜始まり (JIS / 業務週)
  const s = startOfDay(d)
  const day = s.getDay() // 0=Sun .. 6=Sat
  const diff = day === 0 ? 6 : day - 1
  return addDays(s, -diff)
}

function startOfYear(d: Date): Date {
  return new Date(d.getFullYear(), 0, 1)
}

function endOfYear(d: Date): Date {
  return new Date(d.getFullYear(), 11, 31)
}

/** 2 桁年を 19YY か 20YY に補正する。
 * 現在年 (YY 部) + 1 以下なら 20YY, それ以外は 19YY。
 */
function expandYY(yy: number, now: Date): number {
  if (yy >= 100) return yy
  const curYY = now.getFullYear() % 100
  return yy <= curYY + 1 ? 2000 + yy : 1900 + yy
}

interface Hit {
  from: Date | null
  to: Date | null
  matchedText: string
  labelJa: string
  labelEn: string
  confidence: PeriodConfidence
}

function buildResult(hit: Hit | null, lang: 'ja' | 'en'): ParsedPeriod {
  if (hit == null) {
    return {
      dateFrom: null,
      dateTo: null,
      label: '',
      confidence: 'none',
      matchedText: '',
    }
  }
  return {
    dateFrom: hit.from ? fmt(hit.from) : null,
    dateTo: hit.to ? fmt(hit.to) : null,
    label: lang === 'en' ? hit.labelEn : hit.labelJa,
    confidence: hit.confidence,
    matchedText: hit.matchedText,
  }
}

// ─────────────────────────────────────────────────────────────
// 日付パーツのパース
// ─────────────────────────────────────────────────────────────

interface RawDate {
  y: number | null // null = year not specified
  m: number
  d: number | null // null = day not specified (= 月単位)
}

/** "2025/3/1", "25/3/1", "2025-03-01", "2025年3月1日", "3月1日", "25/03" 等を 1 個ぱくっと食う。
 * 返値: { rd, len, text }
 */
function consumeDate(s: string, now: Date): { rd: RawDate; len: number; text: string } | null {
  // YYYY年M月D日 / YYYY年M月
  let m = s.match(/^(\d{4})年(\d{1,2})月(?:(\d{1,2})日)?/)
  if (m) {
    return {
      rd: {
        y: parseInt(m[1], 10),
        m: parseInt(m[2], 10),
        d: m[3] ? parseInt(m[3], 10) : null,
      },
      len: m[0].length,
      text: m[0],
    }
  }
  // M月D日 (年なし)
  m = s.match(/^(\d{1,2})月(\d{1,2})日/)
  if (m) {
    return {
      rd: { y: null, m: parseInt(m[1], 10), d: parseInt(m[2], 10) },
      len: m[0].length,
      text: m[0],
    }
  }
  // M月 (年なし、日なし)
  m = s.match(/^(\d{1,2})月(?![\d日])/)
  if (m) {
    return {
      rd: { y: null, m: parseInt(m[1], 10), d: null },
      len: m[0].length,
      text: m[0],
    }
  }
  // YYYY-MM-DD / YYYY/MM/DD
  m = s.match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b/)
  if (m) {
    return {
      rd: { y: parseInt(m[1], 10), m: parseInt(m[2], 10), d: parseInt(m[3], 10) },
      len: m[0].length,
      text: m[0],
    }
  }
  // YY/MM/DD
  m = s.match(/^(\d{2})[-/](\d{1,2})[-/](\d{1,2})\b/)
  if (m) {
    return {
      rd: {
        y: expandYY(parseInt(m[1], 10), now),
        m: parseInt(m[2], 10),
        d: parseInt(m[3], 10),
      },
      len: m[0].length,
      text: m[0],
    }
  }
  // YYYY-MM / YYYY/MM
  m = s.match(/^(\d{4})[-/](\d{1,2})\b(?!\s*[-/]\s*\d)/)
  if (m) {
    return {
      rd: { y: parseInt(m[1], 10), m: parseInt(m[2], 10), d: null },
      len: m[0].length,
      text: m[0],
    }
  }
  // YY/MM
  m = s.match(/^(\d{2})[-/](\d{1,2})\b(?!\s*[-/]\s*\d)/)
  if (m) {
    return {
      rd: { y: expandYY(parseInt(m[1], 10), now), m: parseInt(m[2], 10), d: null },
      len: m[0].length,
      text: m[0],
    }
  }
  return null
}

/** RawDate を実 Date 範囲に変換 ({from, to}). 日付指定なら from=to=その日, 月指定なら月の頭〜末. */
function rdToRange(rd: RawDate, now: Date): { from: Date; to: Date } {
  const y = rd.y ?? now.getFullYear()
  // ambiguous month-day without year: 直近 12 ヶ月で過去側に倒す
  if (rd.y == null && rd.d != null) {
    const candidate = new Date(y, rd.m - 1, rd.d)
    if (candidate.getTime() > now.getTime()) {
      candidate.setFullYear(candidate.getFullYear() - 1)
    }
    return { from: candidate, to: candidate }
  }
  if (rd.y == null && rd.d == null) {
    const candidate = new Date(y, rd.m - 1, 1)
    if (candidate.getTime() > now.getTime()) {
      candidate.setFullYear(candidate.getFullYear() - 1)
    }
    return { from: startOfMonth(candidate), to: endOfMonth(candidate) }
  }
  if (rd.d == null) {
    const d = new Date(y, rd.m - 1, 1)
    return { from: startOfMonth(d), to: endOfMonth(d) }
  }
  const d = new Date(y, rd.m - 1, rd.d)
  return { from: d, to: d }
}

function labelDate(d: Date, lang: 'ja' | 'en'): string {
  void lang
  return fmt(d)
}

// ─────────────────────────────────────────────────────────────
// detectors
// ─────────────────────────────────────────────────────────────

/** 範囲コネクタ (〜 ~ から…まで to – -). 戻り値: コネクタ長 + open-end flag. */
const RANGE_CONNECTOR_RE =
  /^\s*(から(?:今|現在)まで|から今まで|から現在まで|から|〜|~|to|–|—|-)\s*/i

function tryAbsoluteRange(input: string, now: Date): Hit | null {
  // 任意位置で「日付 + コネクタ + 日付」 / 「日付 + から (今|現在) まで」 をスキャン
  for (let i = 0; i < input.length; i++) {
    const sub = input.slice(i)
    const left = consumeDate(sub, now)
    if (!left) continue
    const afterLeft = sub.slice(left.len)
    const conn = afterLeft.match(RANGE_CONNECTOR_RE)
    if (!conn) {
      // 単独の日付 → 後段 (single date) で扱うので continue
      continue
    }
    const connText = conn[1]
    const isOpenEnd =
      /から(?:今|現在)まで/.test(connText) || /から今まで|から現在まで/.test(connText)
    const afterConn = afterLeft.slice(conn[0].length)
    const leftRange = rdToRange(left.rd, now)

    if (isOpenEnd) {
      return {
        from: leftRange.from,
        to: startOfDay(now),
        matchedText: input.slice(i, i + left.len + conn[0].length),
        labelJa: `${labelDate(leftRange.from, 'ja')} 〜 今日`,
        labelEn: `${labelDate(leftRange.from, 'en')} → today`,
        confidence: 'exact',
      }
    }
    const right = consumeDate(afterConn, now)
    if (right) {
      const rightRange = rdToRange(right.rd, now)
      return {
        from: leftRange.from,
        to: rightRange.to,
        matchedText: input.slice(
          i,
          i + left.len + conn[0].length + right.len,
        ),
        labelJa: `${fmt(leftRange.from)} 〜 ${fmt(rightRange.to)}`,
        labelEn: `${fmt(leftRange.from)} → ${fmt(rightRange.to)}`,
        confidence: 'exact',
      }
    }
    // コネクタ後に 「今」「現在」「today」 などのキーワード
    const endKw = afterConn.match(/^\s*(今|現在|today|now)\b/i)
    if (endKw) {
      return {
        from: leftRange.from,
        to: startOfDay(now),
        matchedText: input.slice(
          i,
          i + left.len + conn[0].length + endKw[0].length,
        ),
        labelJa: `${fmt(leftRange.from)} 〜 今日`,
        labelEn: `${fmt(leftRange.from)} → today`,
        confidence: 'exact',
      }
    }
  }
  return null
}

function trySingleAbsolute(input: string, now: Date): Hit | null {
  for (let i = 0; i < input.length; i++) {
    const sub = input.slice(i)
    const got = consumeDate(sub, now)
    if (!got) continue
    const range = rdToRange(got.rd, now)
    return {
      from: range.from,
      to: range.to,
      matchedText: sub.slice(0, got.len),
      labelJa: range.from.getTime() === range.to.getTime()
        ? fmt(range.from)
        : `${fmt(range.from)} 〜 ${fmt(range.to)}`,
      labelEn: range.from.getTime() === range.to.getTime()
        ? fmt(range.from)
        : `${fmt(range.from)} → ${fmt(range.to)}`,
      confidence: 'exact',
    }
  }
  return null
}

function tryRelativeKeyword(input: string, now: Date): Hit | null {
  const today = startOfDay(now)
  // 今日 / today
  if (/今日|本日|today/i.test(input)) {
    const m = input.match(/今日|本日|today/i)!
    return {
      from: today,
      to: today,
      matchedText: m[0],
      labelJa: '今日',
      labelEn: 'today',
      confidence: 'exact',
    }
  }
  // 昨日 / yesterday
  if (/昨日|yesterday/i.test(input)) {
    const m = input.match(/昨日|yesterday/i)!
    const d = addDays(today, -1)
    return {
      from: d,
      to: d,
      matchedText: m[0],
      labelJa: '昨日',
      labelEn: 'yesterday',
      confidence: 'exact',
    }
  }
  // 今週 / this week
  if (/今週|this\s+week/i.test(input)) {
    const m = input.match(/今週|this\s+week/i)!
    const s = startOfWeek(today)
    return {
      from: s,
      to: addDays(s, 6),
      matchedText: m[0],
      labelJa: '今週',
      labelEn: 'this week',
      confidence: 'exact',
    }
  }
  // 先週 / last week
  if (/先週|last\s+week/i.test(input)) {
    const m = input.match(/先週|last\s+week/i)!
    const s = addDays(startOfWeek(today), -7)
    return {
      from: s,
      to: addDays(s, 6),
      matchedText: m[0],
      labelJa: '先週',
      labelEn: 'last week',
      confidence: 'exact',
    }
  }
  // 今月 / this month
  if (/今月|this\s+month/i.test(input)) {
    const m = input.match(/今月|this\s+month/i)!
    return {
      from: startOfMonth(today),
      to: endOfMonth(today),
      matchedText: m[0],
      labelJa: '今月',
      labelEn: 'this month',
      confidence: 'exact',
    }
  }
  // 先月 / last month
  if (/先月|last\s+month/i.test(input)) {
    const m = input.match(/先月|last\s+month/i)!
    const ref = addMonths(today, -1)
    return {
      from: startOfMonth(ref),
      to: endOfMonth(ref),
      matchedText: m[0],
      labelJa: '先月',
      labelEn: 'last month',
      confidence: 'exact',
    }
  }
  // 今年 / this year
  if (/今年|this\s+year/i.test(input)) {
    const m = input.match(/今年|this\s+year/i)!
    return {
      from: startOfYear(today),
      to: endOfYear(today),
      matchedText: m[0],
      labelJa: '今年',
      labelEn: 'this year',
      confidence: 'exact',
    }
  }
  // 去年 / 昨年 / last year
  if (/去年|昨年|last\s+year/i.test(input)) {
    const m = input.match(/去年|昨年|last\s+year/i)!
    const ref = addYears(today, -1)
    return {
      from: startOfYear(ref),
      to: endOfYear(ref),
      matchedText: m[0],
      labelJa: '去年',
      labelEn: 'last year',
      confidence: 'exact',
    }
  }
  return null
}

function tryRelativeDuration(input: string, now: Date): Hit | null {
  const today = startOfDay(now)
  // 直近 N 日/週/ヶ月/年, 過去 N 日/週/月, この/ここ N 日/週/ヶ月
  let m = input.match(
    /(直近|過去|この|ここ)\s*(\d{1,3})\s*(日|週間?|ヶ月|か月|カ月|月|年)/,
  )
  if (m) {
    const n = parseInt(m[2], 10)
    const unit = m[3]
    let from = today
    let labelUnitJa = unit
    let labelUnitEn = ''
    if (unit === '日') {
      from = addDays(today, -(n - 1))
      labelUnitEn = n === 1 ? 'day' : 'days'
    } else if (unit.startsWith('週')) {
      from = addDays(today, -(n * 7 - 1))
      labelUnitEn = n === 1 ? 'week' : 'weeks'
    } else if (unit === '年') {
      from = addYears(today, -n)
      from = addDays(from, 1)
      labelUnitEn = n === 1 ? 'year' : 'years'
    } else {
      // ヶ月 / か月 / カ月 / 月
      from = addMonths(today, -n)
      from = addDays(from, 1)
      labelUnitJa = 'ヶ月'
      labelUnitEn = n === 1 ? 'month' : 'months'
    }
    return {
      from,
      to: today,
      matchedText: m[0],
      labelJa: `直近${n}${labelUnitJa}`,
      labelEn: `past ${n} ${labelUnitEn}`,
      confidence: 'exact',
    }
  }
  // past/last N days/weeks/months/years
  m = input.match(/(past|last)\s+(\d{1,3})\s+(day|week|month|year)s?/i)
  if (m) {
    const n = parseInt(m[2], 10)
    const unit = m[3].toLowerCase()
    let from = today
    if (unit === 'day') from = addDays(today, -(n - 1))
    else if (unit === 'week') from = addDays(today, -(n * 7 - 1))
    else if (unit === 'year') from = addDays(addYears(today, -n), 1)
    else from = addDays(addMonths(today, -n), 1)
    return {
      from,
      to: today,
      matchedText: m[0],
      labelJa: `直近${n}${unit === 'day' ? '日' : unit === 'week' ? '週' : unit === 'year' ? '年' : 'ヶ月'}`,
      labelEn: `past ${n} ${unit}${n === 1 ? '' : 's'}`,
      confidence: 'exact',
    }
  }
  return null
}

function trySinceKeyword(input: string, now: Date): Hit | null {
  // since YYYY-MM(-DD)? or since 2025/3 etc.
  const m = input.match(/since\s+/i)
  if (!m) return null
  const after = input.slice(m.index! + m[0].length)
  const got = consumeDate(after, now)
  if (!got) return null
  const range = rdToRange(got.rd, now)
  return {
    from: range.from,
    to: startOfDay(now),
    matchedText: input.slice(m.index!, m.index! + m[0].length + got.len),
    labelJa: `${fmt(range.from)} 〜 今日`,
    labelEn: `since ${fmt(range.from)}`,
    confidence: 'exact',
  }
}

// ─────────────────────────────────────────────────────────────
// entry point
// ─────────────────────────────────────────────────────────────

export function parsePeriod(
  input: string,
  now: Date = new Date(),
  lang: 'ja' | 'en' = 'ja',
): ParsedPeriod {
  if (!input || !input.trim()) {
    return buildResult(null, lang)
  }

  // 1. 絶対範囲
  const a = tryAbsoluteRange(input, now)
  if (a) return buildResult(a, lang)

  // 2. since <date> (en)
  const sinceHit = trySinceKeyword(input, now)
  if (sinceHit) return buildResult(sinceHit, lang)

  // 3. 相対 duration ("直近3ヶ月" は単一月 "3月" より優先)
  const dur = tryRelativeDuration(input, now)
  if (dur) return buildResult(dur, lang)

  // 4. relative keyword (今月, 先月, today...)
  const rel = tryRelativeKeyword(input, now)
  if (rel) return buildResult(rel, lang)

  // 5. 単一絶対
  const single = trySingleAbsolute(input, now)
  if (single) return buildResult(single, lang)

  return buildResult(null, lang)
}
