/**
 * ラグ相関・変動係数ランキングは coach / analyst 限定の探索的な解析。
 * 旧実装は RoleGuard の許可に 'player' を入れており、player に描画されていた。
 * player には何も描かず、analyst / coach / admin の表示は従来どおり。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'
import type { UserRole } from '@/types'

let mockRole: UserRole | null = 'player'

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    role: mockRole,
    hasRole: (allowed: UserRole[]) =>
      !mockRole ? false : mockRole === 'admin' ? true : allowed.includes(mockRole),
  }),
}))
vi.mock('@/hooks/useConditions', () => ({
  useConditions: () => ({ data: [], isLoading: false }),
}))

import { ConditionLagCorrelation } from '../ConditionLagCorrelation'
import { ConditionVolatilityRanking } from '../ConditionVolatilityRanking'

const cards = [
  ['ConditionLagCorrelation', ConditionLagCorrelation],
  ['ConditionVolatilityRanking', ConditionVolatilityRanking],
] as const

beforeEach(() => {
  mockRole = 'player'
})

describe.each(cards)('%s role guard', (_name, Card) => {
  it('player: 何も描画しない', () => {
    mockRole = 'player'
    const { container } = render(<Card playerId={1} isLight={false} />)
    expect(container.innerHTML).toBe('')
  })

  it.each(['analyst', 'coach', 'admin'] as const)('%s: 従来どおり描画する', (role) => {
    mockRole = role
    const { container } = render(<Card playerId={1} isLight={false} />)
    expect(container.querySelector('section')).not.toBeNull()
  })
})
