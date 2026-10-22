// 防ぐ事象 (監査 #796): 分析期間の「今日 / 1ヶ月前」を UTC 日付へ変換すると、
// 日本時間 0:00-8:59 は 1 日ずれる。タイムゾーンを固定して境界を確かめる。
process.env.TZ = 'Asia/Tokyo'

import { describe, expect, it } from 'vitest'
import {
  formatLocalDate,
  isReversedRange,
  localDateDaysAgo,
  localDateMonthsAgo,
  localDateYearsAgo,
  presetFromDate,
  todayLocal,
} from '@/utils/localDate'

// 2026-10-22 のローカル (JST) 時刻
const jst = (h: number, m: number) => new Date(2026, 9, 22, h, m, 0)

describe('local date helpers in Asia/Tokyo', () => {
  it('runs in the intended timezone', () => {
    expect(new Date(2026, 9, 22, 0, 0).getTimezoneOffset()).toBe(-540)
  })

  it('today is the local date at 00:00, 05:00, 08:59 and 09:00', () => {
    for (const [h, m] of [[0, 0], [5, 0], [8, 59], [9, 0], [23, 59]]) {
      expect(todayLocal(jst(h, m))).toBe('2026-10-22')
    }
  })

  it('shows why the UTC conversion was wrong at 05:00 JST', () => {
    expect(jst(5, 0).toISOString().split('T')[0]).toBe('2026-10-21')
    expect(formatLocalDate(jst(5, 0))).toBe('2026-10-22')
  })

  it('month / year / day presets use the local calendar at 05:00 JST', () => {
    const now = jst(5, 0)
    expect(localDateMonthsAgo(1, now)).toBe('2026-09-22')
    expect(localDateMonthsAgo(3, now)).toBe('2026-07-22')
    expect(localDateYearsAgo(1, now)).toBe('2025-10-22')
    expect(localDateDaysAgo(7, now)).toBe('2026-10-15')
  })

  it('presetFromDate matches the same boundary values', () => {
    expect(presetFromDate('1m', jst(5, 0))).toBe('2026-09-22')
    expect(presetFromDate('1m', jst(9, 0))).toBe('2026-09-22')
    expect(presetFromDate('6m', jst(0, 0))).toBe('2026-04-22')
    expect(presetFromDate('1y', jst(8, 59))).toBe('2025-10-22')
    expect(presetFromDate('all', jst(5, 0))).toBe('')
  })
})

describe('calendar-month subtraction clamps to the end of the target month (audit #952)', () => {
  const at = (y: number, m: number, d: number) => new Date(y, m - 1, d, 12, 0, 0)

  it('Mar 31 minus 1 month is Feb 28, not Mar 3', () => {
    expect(localDateMonthsAgo(1, at(2026, 3, 31))).toBe('2026-02-28')
    expect(presetFromDate('1m', at(2026, 3, 31))).toBe('2026-02-28')
  })

  it('Mar 31 minus 1 month in a leap year is Feb 29', () => {
    expect(localDateMonthsAgo(1, at(2028, 3, 31))).toBe('2028-02-29')
  })

  it('Aug 31 minus 6 months is Feb 28, and minus 3 months is May 31', () => {
    expect(localDateMonthsAgo(6, at(2026, 8, 31))).toBe('2026-02-28')
    expect(presetFromDate('6m', at(2026, 8, 31))).toBe('2026-02-28')
    expect(localDateMonthsAgo(3, at(2026, 8, 31))).toBe('2026-05-31')
  })

  it('Nov 30 minus 3 months keeps Aug 30 (the day exists)', () => {
    expect(localDateMonthsAgo(3, at(2026, 11, 30))).toBe('2026-08-30')
  })

  it('Jan 31 minus 1 month is Dec 31 of the previous year', () => {
    expect(localDateMonthsAgo(1, at(2026, 1, 31))).toBe('2025-12-31')
  })

  it('Feb 29 minus 1 year is Feb 28 (no Mar 1 overflow)', () => {
    expect(localDateYearsAgo(1, at(2028, 2, 29))).toBe('2027-02-28')
    expect(presetFromDate('1y', at(2028, 2, 29))).toBe('2027-02-28')
    expect(localDateYearsAgo(4, at(2028, 2, 29))).toBe('2024-02-29')
  })

  it('Feb 29 minus 12 months equals minus 1 year', () => {
    expect(localDateMonthsAgo(12, at(2028, 2, 29))).toBe(localDateYearsAgo(1, at(2028, 2, 29)))
  })
})

describe('isReversedRange', () => {
  it('rejects only a start date after the end date', () => {
    expect(isReversedRange('2026-03-01', '2026-01-01')).toBe(true)
    expect(isReversedRange('2026-01-01', '2026-01-01')).toBe(false)
    expect(isReversedRange('2026-01-01', '2026-03-01')).toBe(false)
    expect(isReversedRange('', '2026-03-01')).toBe(false)
    expect(isReversedRange('2026-03-01', null)).toBe(false)
  })
})
