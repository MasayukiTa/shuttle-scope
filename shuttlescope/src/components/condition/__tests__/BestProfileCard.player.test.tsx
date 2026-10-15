/**
 * ベストプロフィール: player には勝率 (in/outside・改善見込み) と
 * 「勝った試合 / 負けた試合」の対比文を出さない。
 * API は player 応答から win_rate_in_profile / win_rate_outside を落とす。
 * analyst / coach / admin の表示は従来どおり。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'
import type { UserRole } from '@/types'

let mockRole: UserRole | null = 'player'

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ role: mockRole }),
}))

const factor = {
  key: 'sleep_hours', current: 6.5, target_min: 7, target_max: 8, gap: 0.5,
  target_mean: 7.5, rest_mean: 6.2, direction: 'higher_when_winning',
}
let mockData: Record<string, unknown>
vi.mock('@/hooks/useConditionAnalytics', () => ({
  useBestProfile: () => ({ data: mockData, isLoading: false, error: null }),
}))

import { BestProfileCard } from '../BestProfileCard'

const playerData = { n_matches: 12, win_rate_in_profile: null, win_rate_outside: null, key_factors: [factor] }
const coachData = { n_matches: 12, win_rate_in_profile: 0.7, win_rate_outside: 0.4, key_factors: [factor] }

beforeEach(() => {
  mockRole = 'player'
  mockData = playerData
})

describe('BestProfileCard', () => {
  it('player: 勝率・改善見込み・勝敗の対比文を描かず、目標レンジは残す', () => {
    const { container } = render(<BestProfileCard playerId={1} isLight={false} />)
    const text = container.textContent ?? ''
    expect(text).not.toMatch(/NaN|undefined/)
    expect(text).not.toContain('%')
    expect(text).not.toMatch(/勝った試合|負けた試合|勝率/)
    expect(text).toContain('7.0〜8.0')
  })

  it('player: API が (誤って) 勝率を返しても描かない (ロールで fail-closed)', () => {
    mockData = coachData
    const { container } = render(<BestProfileCard playerId={1} isLight={false} />)
    const text = container.textContent ?? ''
    expect(text).not.toContain('70.0%')
    expect(text).not.toMatch(/勝った試合|負けた試合/)
  })

  it.each(['analyst', 'coach', 'admin'] as UserRole[])('%s: 従来どおり勝率・改善見込み・対比文を描く', (r) => {
    mockRole = r
    mockData = coachData
    const { container } = render(<BestProfileCard playerId={1} isLight={false} />)
    const text = container.textContent ?? ''
    expect(text).toContain('70.0%')
    expect(text).toContain('40.0%')
    expect(text).toContain('勝った試合では')
  })
})
