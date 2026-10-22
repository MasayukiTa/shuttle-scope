/**
 * ベストプロフィール: 観察された関連を、目標値・改善見込み・上げ下げの助言へ変換しない (監査 #75 / #222)。
 */
import { describe, it, expect, vi } from 'vitest'
import { render } from '@testing-library/react'
import type { UserRole } from '@/types'

let mockRole: UserRole | null = 'coach'

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ role: mockRole }),
}))

const factor = {
  key: 'muscle_mass_kg', current: 36, target_min: 30, target_max: 30, gap: -6,
  target_mean: 30, rest_mean: 36, direction: 'lower_when_winning',
}
const data = { n_matches: 3, win_rate_in_profile: 0.7, win_rate_outside: 0.2, key_factors: [factor] }
vi.mock('@/hooks/useConditionAnalytics', () => ({
  useBestProfile: () => ({ data, isLoading: false, error: null }),
}))

import { BestProfileCard } from '../BestProfileCard'

describe('BestProfileCard: 因果・助言の言い切りをしない', () => {
  it('coach: 「見込み」「目標」「上げ下げ」を出さず、観察された関連と注意書きを出す', () => {
    mockRole = 'coach'
    const { container } = render(<BestProfileCard playerId={1} isLight={false} />)
    const text = container.textContent ?? ''
    expect(text).not.toContain('見込み')
    expect(text).not.toContain('目標 [')
    expect(text).not.toMatch(/[↑↓]/)
    expect(text).not.toMatch(/上げると|下げると/)
    expect(text).toContain('観察された関連')
    expect(text).toContain('目標値でも改善の指示でもなく')
  })

  it('player: 注意書きは出るが、勝率や勝敗の対比は出さない', () => {
    mockRole = 'player'
    const { container } = render(<BestProfileCard playerId={1} isLight={false} />)
    const text = container.textContent ?? ''
    expect(text).toContain('目標値でも改善の指示でもなく')
    expect(text).not.toMatch(/勝った試合|負けた試合|勝率|見込み/)
  })
})
