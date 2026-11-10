/**
 * ベストプロフィール: 観測範囲の横に効果量 (標準化差 |d|) を併記する (監査 #223)。
 * 範囲を「最適な個人目標値」ではなく「観測された差の大きさ」として読ませるための表示。
 * 分析指標なので player には出さない (coach 以上のみ)。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import type { UserRole } from '@/types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (opts && 'd' in opts) return `effect:${opts.d as string}`
      if (opts && 'r' in opts) return `target:${opts.r as string}`
      if (opts && 'v' in opts) return `observed:${opts.v as string}`
      if (opts && 'n' in opts) return `${key}:${opts.n as number}`
      return key
    },
  }),
}))

let mockRole: UserRole | null = 'coach'
vi.mock('@/hooks/useAuth', () => ({ useAuth: () => ({ role: mockRole }) }))

const mockUseBestProfile = vi.fn()
vi.mock('@/hooks/useConditionAnalytics', () => ({
  useBestProfile: (playerId: number) => mockUseBestProfile(playerId),
}))

vi.mock('@/components/common/MIcon', () => ({ MIcon: () => null }))

import { BestProfileCard } from '@/components/condition/BestProfileCard'

function setData(keyFactors: Array<Record<string, unknown>>, nMatches = 20) {
  mockUseBestProfile.mockReturnValue({
    data: { key_factors: keyFactors, n_matches: nMatches },
    isLoading: false,
    error: null,
  })
}

beforeEach(() => {
  mockRole = 'coach'
  mockUseBestProfile.mockReset()
})

describe('BestProfileCard effect size (audit #223)', () => {
  it('coach: renders effect size next to a real observed range', () => {
    setData([{ key: 'muscle_mass_kg', current: 52, target_min: 51.9, target_max: 52.6, importance: -0.42 }])
    render(<BestProfileCard playerId={1} isLight={false} />)
    expect(screen.getByText(/effect:0\.42/)).toBeInTheDocument()
    expect(screen.getByText(/target:51\.9\u301c52\.6kg/)).toBeInTheDocument()
  })

  it('player: never shows effect size', () => {
    mockRole = 'player'
    setData([{ key: 'muscle_mass_kg', current: 52, target_min: 51.9, target_max: 52.6, importance: -0.42 }])
    render(<BestProfileCard playerId={1} isLight={false} />)
    expect(screen.queryByText(/effect:/)).toBeNull()
    expect(screen.getByText(/target:51\.9\u301c52\.6kg/)).toBeInTheDocument()
  })

  it('coach: no effect size label when importance is missing', () => {
    setData([{ key: 'muscle_mass_kg', current: 52, target_min: 51.9, target_max: 52.6 }])
    render(<BestProfileCard playerId={1} isLight={false} />)
    expect(screen.queryByText(/effect:/)).toBeNull()
  })
})
