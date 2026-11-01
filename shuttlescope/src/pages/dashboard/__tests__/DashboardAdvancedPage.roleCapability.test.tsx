/**
 * 監査#747: Advanced ページの research tier ウィジェットを
 * backend 権限 (require_admin_or_analyst) と揃える。
 * - spatial_density / opponent_type_affinity は admin/analyst のみ。
 *   coach は backend が 403 なので画面にも出さない。
 * - coach 向けの OpponentStats は従来どおり表示する。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { UserRole } from '@/types'

let mockRole: UserRole | null = 'coach'

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    role: mockRole,
    hasRole: (allowed: UserRole[]) => (!mockRole ? false : mockRole === 'admin' ? true : allowed.includes(mockRole)),
  }),
}))
vi.mock('@/api/client', () => ({ apiGet: vi.fn(async () => ({ success: true, data: {} })), API_BASE_URL: '' }))
vi.mock('@/hooks/useAnalysisMeta', () => ({ useAnalysisMeta: () => ({ getMeta: () => ({}), isOnHold: () => false }) }))
vi.mock('@/utils/analytics', () => ({ analyticsViewLifecycle: () => () => {} }))

// マーカーを出す子コンポーネント (research tier と coach-legit の区別用)
vi.mock('@/components/analysis/SpatialDensityMap', () => ({ SpatialDensityMap: () => <div>MOCK_SPATIAL_DENSITY</div> }))
vi.mock('@/components/analysis/OpponentTypeAffinity', () => ({ OpponentTypeAffinity: () => <div>MOCK_OPP_AFFINITY</div> }))
vi.mock('@/components/analysis/OpponentStats', () => ({ OpponentStats: () => <div>MOCK_OPP_STATS</div> }))
vi.mock('@/components/analysis/PreLossPatterns', () => ({ PreLossPatterns: () => <div>MOCK_PRELOSS</div> }))
vi.mock('@/components/analysis/FirstReturnAnalysis', () => ({ FirstReturnAnalysis: () => <div>MOCK_FIRSTRETURN</div> }))
vi.mock('@/components/analysis/OpponentAdaptiveShots', () => ({ OpponentAdaptiveShots: () => null }))
vi.mock('@/components/analysis/ShotWinLoss', () => ({ ShotWinLoss: () => null }))
vi.mock('@/components/analysis/RallyLengthWinRate', () => ({ RallyLengthWinRate: () => null }))
vi.mock('@/components/analysis/PressurePerformance', () => ({ PressurePerformance: () => null }))
vi.mock('@/components/analysis/TransitionMatrix', () => ({ TransitionMatrix: () => null }))
vi.mock('@/components/analysis/TemporalPerformance', () => ({ TemporalPerformance: () => null }))
vi.mock('@/components/analysis/PostLongRallyStats', () => ({ PostLongRallyStats: () => null }))
vi.mock('@/components/analysis/PreMatchObservationAnalytics', () => ({ PreMatchObservationAnalytics: () => null }))
vi.mock('@/components/analysis/DoublesAnalysis', () => ({ DoublesAnalysis: () => null }))
vi.mock('@/components/analysis/PairPlaystyle', () => ({ PairPlaystyle: () => null }))
vi.mock('@/components/analysis/PairSynergyCard', () => ({ PairSynergyCard: () => null }))
vi.mock('@/components/analysis/WinLossComparison', () => ({ WinLossComparison: () => null }))
vi.mock('@/components/analysis/TournamentComparison', () => ({ TournamentComparison: () => null }))

import { DashboardAdvancedPage } from '../DashboardAdvancedPage'

const filters = { result: 'all', tournamentLevel: null, dateFrom: null, dateTo: null } as never

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <DashboardAdvancedPage playerId={1} filters={filters} matches={[] as never} sortedPlayers={[] as never} />
    </QueryClientProvider>,
  )
}

beforeEach(() => { mockRole = 'coach' })

describe('DashboardAdvancedPage research tier ロールゲート (#747)', () => {
  it('coach: 空間セクションで SpatialDensityMap を出さない (他は出す)', () => {
    const { container, getByText } = wrap()
    fireEvent.click(getByText('空間'))
    expect(container.textContent).toContain('MOCK_PRELOSS')
    expect(container.textContent).toContain('MOCK_FIRSTRETURN')
    expect(container.textContent).not.toContain('MOCK_SPATIAL_DENSITY')
  })

  it.each(['analyst', 'admin'] as UserRole[])('%s: 空間セクションで SpatialDensityMap を出す', (r) => {
    mockRole = r
    const { container, getByText } = wrap()
    fireEvent.click(getByText('空間'))
    expect(container.textContent).toContain('MOCK_SPATIAL_DENSITY')
  })

  it('coach: 対戦相手セクションで OpponentTypeAffinity を出さず、OpponentStats は出す', () => {
    const { container, getByText } = wrap()
    fireEvent.click(getByText('対戦相手'))
    expect(container.textContent).toContain('MOCK_OPP_STATS')
    expect(container.textContent).not.toContain('MOCK_OPP_AFFINITY')
  })

  it.each(['analyst', 'admin'] as UserRole[])('%s: 対戦相手セクションで OpponentTypeAffinity を出す', (r) => {
    mockRole = r
    const { container, getByText } = wrap()
    fireEvent.click(getByText('対戦相手'))
    expect(container.textContent).toContain('MOCK_OPP_AFFINITY')
    expect(container.textContent).toContain('MOCK_OPP_STATS')
  })
})
