/**
 * parsePeriod のユニットテスト。
 *
 * now を必ず固定して呼ぶ (テスト独立性)。
 * 各 branch + edge case を網羅:
 *   - 絶対範囲 (YYYY/M/D 〜 YYYY/M/D)
 *   - 絶対 + open-end (... から今まで)
 *   - 2 桁年補正 (25/3 → 2025/3, 99/3 → 1999/3)
 *   - 単一月/年キーワード (今月, 先月, 今年, 去年, 2025年3月)
 *   - 相対 duration (直近3ヶ月, past 30 days, 過去2週間, 直近1年)
 *   - today / yesterday / this week / last week
 *   - since YYYY-MM
 *   - 月境界 / 閏年 / 年またぎ / "3/1" だけ与えたケース
 *   - 何も拾えないケース
 */
import { describe, expect, it } from 'vitest'
import { parsePeriod } from '@/utils/parsePeriod'

const NOW = new Date(2026, 4, 23) // 2026-05-23 (月曜)

describe('parsePeriod — empty / no match', () => {
  it('空文字は none', () => {
    const r = parsePeriod('', NOW)
    expect(r.confidence).toBe('none')
    expect(r.dateFrom).toBeNull()
    expect(r.dateTo).toBeNull()
  })

  it('日付情報を含まない一般文は none', () => {
    const r = parsePeriod('スマッシュの伸びしろを教えて', NOW)
    expect(r.confidence).toBe('none')
  })
})

describe('parsePeriod — 絶対範囲', () => {
  it('2025/3/1 から 2025/4/30', () => {
    const r = parsePeriod('2025/3/1 から 2025/4/30 の試合', NOW)
    expect(r.confidence).toBe('exact')
    expect(r.dateFrom).toBe('2025-03-01')
    expect(r.dateTo).toBe('2025-04-30')
  })

  it('ISO ハイフン形式', () => {
    const r = parsePeriod('2024-01-15 〜 2024-02-15', NOW)
    expect(r.dateFrom).toBe('2024-01-15')
    expect(r.dateTo).toBe('2024-02-15')
  })

  it('en: 2025-03-01 to 2025-04-30', () => {
    const r = parsePeriod('between 2025-03-01 to 2025-04-30', NOW, 'en')
    expect(r.dateFrom).toBe('2025-03-01')
    expect(r.dateTo).toBe('2025-04-30')
    expect(r.label).toContain('2025-03-01')
  })
})

describe('parsePeriod — open-end', () => {
  it('25/03 から 今まで → 2025-03-01 .. NOW', () => {
    const r = parsePeriod('25/03から今まで', NOW)
    expect(r.confidence).toBe('exact')
    expect(r.dateFrom).toBe('2025-03-01')
    expect(r.dateTo).toBe('2026-05-23')
  })

  it('2024/6/1 から 現在まで', () => {
    const r = parsePeriod('2024/6/1から現在まで', NOW)
    expect(r.dateFrom).toBe('2024-06-01')
    expect(r.dateTo).toBe('2026-05-23')
  })

  it('since 2025-03', () => {
    const r = parsePeriod('show me stats since 2025-03', NOW, 'en')
    expect(r.dateFrom).toBe('2025-03-01')
    expect(r.dateTo).toBe('2026-05-23')
    expect(r.label.toLowerCase()).toContain('since')
  })
})

describe('parsePeriod — 2 桁年補正', () => {
  it('25/03 → 2025-03', () => {
    const r = parsePeriod('25/03の試合', NOW)
    expect(r.dateFrom).toBe('2025-03-01')
    expect(r.dateTo).toBe('2025-03-31')
  })

  it('99/03 → 1999-03 (cutoff = curYY+1)', () => {
    const r = parsePeriod('99/03', NOW)
    expect(r.dateFrom).toBe('1999-03-01')
  })

  it('curYY+1 境界: 27/03 → 2027-03', () => {
    const r = parsePeriod('27/03', NOW)
    expect(r.dateFrom).toBe('2027-03-01')
  })
})

describe('parsePeriod — 単一月/年キーワード', () => {
  it('今月', () => {
    const r = parsePeriod('今月の調子はどう？', NOW)
    expect(r.dateFrom).toBe('2026-05-01')
    expect(r.dateTo).toBe('2026-05-31')
  })

  it('先月', () => {
    const r = parsePeriod('先月の', NOW)
    expect(r.dateFrom).toBe('2026-04-01')
    expect(r.dateTo).toBe('2026-04-30')
  })

  it('今年', () => {
    const r = parsePeriod('今年の成績', NOW)
    expect(r.dateFrom).toBe('2026-01-01')
    expect(r.dateTo).toBe('2026-12-31')
  })

  it('去年', () => {
    const r = parsePeriod('去年と比べて', NOW)
    expect(r.dateFrom).toBe('2025-01-01')
    expect(r.dateTo).toBe('2025-12-31')
  })

  it('2025年3月', () => {
    const r = parsePeriod('2025年3月の試合', NOW)
    expect(r.dateFrom).toBe('2025-03-01')
    expect(r.dateTo).toBe('2025-03-31')
  })

  it('3月1日 (年なし、過去側に倒す)', () => {
    const r = parsePeriod('3月1日の試合', NOW)
    expect(r.dateFrom).toBe('2026-03-01')
    expect(r.dateTo).toBe('2026-03-01')
  })

  it('12月の試合 (年なし、過去) → 2025-12', () => {
    const r = parsePeriod('12月の試合', NOW)
    expect(r.dateFrom).toBe('2025-12-01')
    expect(r.dateTo).toBe('2025-12-31')
  })
})

describe('parsePeriod — 相対 duration', () => {
  it('直近3ヶ月', () => {
    const r = parsePeriod('直近3ヶ月で', NOW)
    expect(r.confidence).toBe('exact')
    expect(r.dateTo).toBe('2026-05-23')
    // 2026-05-23 から 3 ヶ月遡って +1 日 = 2026-02-24
    expect(r.dateFrom).toBe('2026-02-24')
  })

  it('過去2週間', () => {
    const r = parsePeriod('過去2週間の', NOW)
    expect(r.dateTo).toBe('2026-05-23')
    // 14 日間 → 2026-05-10
    expect(r.dateFrom).toBe('2026-05-10')
  })

  it('直近1年', () => {
    const r = parsePeriod('直近1年', NOW)
    expect(r.dateTo).toBe('2026-05-23')
    expect(r.dateFrom).toBe('2025-05-24')
  })

  it('past 30 days', () => {
    const r = parsePeriod('past 30 days', NOW, 'en')
    expect(r.dateTo).toBe('2026-05-23')
    expect(r.dateFrom).toBe('2026-04-24')
  })

  it('last 6 months', () => {
    const r = parsePeriod('last 6 months', NOW, 'en')
    expect(r.dateTo).toBe('2026-05-23')
    expect(r.dateFrom).toBe('2025-11-24')
  })
})

describe('parsePeriod — relative keyword', () => {
  it('today', () => {
    const r = parsePeriod('today', NOW, 'en')
    expect(r.dateFrom).toBe('2026-05-23')
    expect(r.dateTo).toBe('2026-05-23')
  })

  it('昨日', () => {
    const r = parsePeriod('昨日のラリー', NOW)
    expect(r.dateFrom).toBe('2026-05-22')
    expect(r.dateTo).toBe('2026-05-22')
  })

  it('今週 (月曜始まり)', () => {
    // NOW = 2026-05-23 (土) → 週は 2026-05-18(月)〜2026-05-24(日)
    const r = parsePeriod('今週', NOW)
    expect(r.dateFrom).toBe('2026-05-18')
    expect(r.dateTo).toBe('2026-05-24')
  })

  it('先週', () => {
    const r = parsePeriod('先週の', NOW)
    expect(r.dateFrom).toBe('2026-05-11')
    expect(r.dateTo).toBe('2026-05-17')
  })
})

describe('parsePeriod — edge cases', () => {
  it('閏年 2024 年 2 月の月末は 29', () => {
    const r = parsePeriod('2024年2月', NOW)
    expect(r.dateFrom).toBe('2024-02-01')
    expect(r.dateTo).toBe('2024-02-29')
  })

  it('非閏年 2025/2 は 28', () => {
    const r = parsePeriod('2025/2', NOW)
    expect(r.dateFrom).toBe('2025-02-01')
    expect(r.dateTo).toBe('2025-02-28')
  })

  it('年またぎ open-end: 2025/12/1 から今まで', () => {
    const r = parsePeriod('2025/12/1から今まで', NOW)
    expect(r.dateFrom).toBe('2025-12-01')
    expect(r.dateTo).toBe('2026-05-23')
  })

  it('priority: "直近3ヶ月" は "3ヶ月" 内の数字に引っ張られず duration', () => {
    const r = parsePeriod('直近3ヶ月', NOW)
    expect(r.dateTo).toBe('2026-05-23')
  })

  it('matchedText は実際にマッチした substring', () => {
    const r = parsePeriod('hello 先月 was good', NOW)
    expect(r.matchedText).toBe('先月')
  })
})
