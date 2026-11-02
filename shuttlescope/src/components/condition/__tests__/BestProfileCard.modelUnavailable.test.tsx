/**
 * 監査 #73: 体調モデルが成立していない (confidence="none") ときは、
 * ベストプロフィールが推奨レンジ・勝率関連を出さず、
 * 明示的な「利用不可」状態だけを出す (モデル不可と推奨値の同居を防ぐ)。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'
import type { UserRole } from '@/types'

let mockRole: UserRole | null = 'coach'

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

beforeEach(() => {
  mockRole = 'coach'
})

describe('BestProfileCard: モデル不可 (confidence=none)', () => {
  it('confidence=none: 推奨レンジ・勝率を出さず、利用不可メッセージを出す', () => {
    mockData = {
      n_matches: 0, confidence: 'none',
      win_rate_in_profile: 0.7, win_rate_outside: 0.4,
      key_factors: [factor],
    }
    const { container } = render(<BestProfileCard playerId={1} isLight={false} />)
    const text = container.textContent ?? ''
    expect(text).toContain('体調モデルがまだ利用できません')
    expect(text).not.toContain('7.0〜8.0')
    expect(text).not.toContain('70.0%')
    expect(text).not.toMatch(/勝った試合|負けた試合/)
  })

  it('confidence=low: 従来どおり推奨レンジを出す (回帰しない)', () => {
    mockData = {
      n_matches: 12, confidence: 'low',
      win_rate_in_profile: null, win_rate_outside: null,
      key_factors: [factor],
    }
    const { container } = render(<BestProfileCard playerId={1} isLight={false} />)
    const text = container.textContent ?? ''
    expect(text).toContain('7.0〜8.0')
    expect(text).not.toContain('体調モデルがまだ利用できません')
  })
})
