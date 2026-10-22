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

describe('isReversedRange', () => {
  it('rejects only a start date after the end date', () => {
    expect(isReversedRange('2026-03-01', '2026-01-01')).toBe(true)
    expect(isReversedRange('2026-01-01', '2026-01-01')).toBe(false)
    expect(isReversedRange('2026-01-01', '2026-03-01')).toBe(false)
    expect(isReversedRange('', '2026-03-01')).toBe(false)
    expect(isReversedRange('2026-03-01', null)).toBe(false)
  })
})
