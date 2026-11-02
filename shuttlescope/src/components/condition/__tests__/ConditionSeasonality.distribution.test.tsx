/**
 * 季節性・曜日効果: 少標本(N=3〜5)の月別平均を単一点だけで見せず、
 * SD(標本標準偏差)と最小〜最大の範囲を併記する (監査 #221)。
 */
import { describe, it, expect, vi } from 'vitest'
import { render } from '@testing-library/react'
import type { ConditionRecord } from '@/hooks/useConditions'

// 同一月(1月) に 4 件、値はそれぞれ異なる (SD>0, rangeは 6.0〜8.0)
const records: ConditionRecord[] = [
  { id: 1, player_id: 1, measured_at: '2026-01-05', condition_type: 'weekly', sleep_hours: 6.0 },
  { id: 2, player_id: 1, measured_at: '2026-01-12', condition_type: 'weekly', sleep_hours: 7.0 },
  { id: 3, player_id: 1, measured_at: '2026-01-19', condition_type: 'weekly', sleep_hours: 8.0 },
  { id: 4, player_id: 1, measured_at: '2026-01-26', condition_type: 'weekly', sleep_hours: 7.0 },
]

vi.mock('@/hooks/useConditions', () => ({
  useConditions: () => ({ data: records, isLoading: false, error: null }),
}))

import { ConditionSeasonality } from '../ConditionSeasonality'

describe('ConditionSeasonality: 少標本で分布を併記', () => {
  it('月別セルに SD と min〜max の範囲を表示する', () => {
    const { container } = render(<ConditionSeasonality playerId={1} isLight={false} />)
    const text = container.textContent ?? ''
    // 平均だけでなく SD が出る
    expect(text).toContain('SD')
    // 範囲の両端 (6.00 と 8.00) が出る
    expect(text).toContain('6.00')
    expect(text).toContain('8.00')
  })
})
