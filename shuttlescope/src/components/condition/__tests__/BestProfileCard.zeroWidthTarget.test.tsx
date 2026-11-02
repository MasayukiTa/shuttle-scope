import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { BestProfileCard } from '@/components/condition/BestProfileCard'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (opts && 'r' in opts) return `target:${opts.r as string}`
      if (opts && 'v' in opts) return `observed:${opts.v as string}`
      if (opts && 'n' in opts) return `${key}:${opts.n as number}`
      return key
    },
  }),
}))

vi.mock('@/hooks/useAuth', () => ({ useAuth: () => ({ role: 'coach' }) }))

const mockUseBestProfile = vi.fn()
vi.mock('@/hooks/useConditionAnalytics', () => ({
  useBestProfile: (playerId: number) => mockUseBestProfile(playerId),
}))

vi.mock('@/components/common/MIcon', () => ({ MIcon: () => null }))

function setData(keyFactors: Array<Record<string, unknown>>, nMatches = 20) {
  mockUseBestProfile.mockReturnValue({
    data: { key_factors: keyFactors, n_matches: nMatches },
    isLoading: false,
    error: null,
  })
}

describe('BestProfileCard zero-width target range (audit #74)', () => {
  it('does not render X~X when target_min === target_max', () => {
    setData([{ key: 'weight_kg', current: 60, target_min: 30, target_max: 30 }])
    render(<BestProfileCard playerId={1} isLight={false} />)
    expect(screen.queryByText(/target:.*〜/)).toBeNull()
    expect(screen.queryByText(/30\.0〜30\.0/)).toBeNull()
    expect(screen.queryByText(/NaN|undefined/)).toBeNull()
  })

  it('renders a single observed value for zero-width', () => {
    setData([{ key: 'weight_kg', current: 60, target_min: 30, target_max: 30 }])
    render(<BestProfileCard playerId={1} isLight={false} />)
    expect(screen.getByText(/observed:30\.0kg/)).toBeInTheDocument()
  })

  it('renders a real interval unchanged (regression)', () => {
    setData([{ key: 'muscle_mass_kg', current: 7.5, target_min: 7, target_max: 8 }])
    render(<BestProfileCard playerId={1} isLight={false} />)
    expect(screen.getByText(/target:7\.0〜8\.0kg/)).toBeInTheDocument()
    expect(screen.queryByText(/observed:/)).toBeNull()
  })
})
