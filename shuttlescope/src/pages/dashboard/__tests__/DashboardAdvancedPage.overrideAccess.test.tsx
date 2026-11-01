/**
 * Item #700: coach は昇格 override API (require_admin_or_analyst) で 403 になるため、
 * frontend も admin/analyst にあわせて取得を有効化する (coach では fetch しない)。
 * また 403/通信失敗を空一覧に折りたたまず、取得失敗を明示文言で出す。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { UserRole } from '@/types'

let mockRole: UserRole | null = 'coach'

vi.mock('@/hooks/useAuth', () => ({ useAuth: () => ({ role: mockRole }) }))

const apiGet = vi.fn()
vi.mock('@/api/client', () => ({ apiGet: (...a: unknown[]) => apiGet(...a) }))

vi.mock('@/utils/analytics', () => ({ analyticsViewLifecycle: () => () => {} }))
vi.mock('@/hooks/useAnalysisMeta', () => ({ useAnalysisMeta: () => ({ getMeta: () => null, isOnHold: () => false }) }))
vi.mock('@/hooks/useCardTheme', () => ({ useCardTheme: () => ({ card: '', cardInner: '', textHeading: '', textSecondary: '', textMuted: '', textFaint: '', badge: '', border: '', isLight: true }) }))
vi.mock('@/components/common/ErrorBoundary', () => ({ ErrorBoundary: () => null }))
vi.mock('@/components/common/RoleGuard', () => ({ RoleGuard: () => null }))
vi.mock('@/components/dashboard/DashboardSectionNav', () => ({ DashboardSectionNav: () => null }))
vi.mock('@/components/analysis/ShotWinLoss', () => ({ ShotWinLoss: () => null }))
vi.mock('@/components/analysis/RallyLengthWinRate', () => ({ RallyLengthWinRate: () => null }))
vi.mock('@/components/analysis/PressurePerformance', () => ({ PressurePerformance: () => null }))
vi.mock('@/components/analysis/TransitionMatrix', () => ({ TransitionMatrix: () => null }))
vi.mock('@/components/analysis/PreLossPatterns', () => ({ PreLossPatterns: () => null }))
vi.mock('@/components/analysis/FirstReturnAnalysis', () => ({ FirstReturnAnalysis: () => null }))
vi.mock('@/components/analysis/SpatialDensityMap', () => ({ SpatialDensityMap: () => null }))
vi.mock('@/components/analysis/TemporalPerformance', () => ({ TemporalPerformance: () => null }))
vi.mock('@/components/analysis/PostLongRallyStats', () => ({ PostLongRallyStats: () => null }))
vi.mock('@/components/analysis/OpponentStats', () => ({ OpponentStats: () => null }))
vi.mock('@/components/analysis/OpponentTypeAffinity', () => ({ OpponentTypeAffinity: () => null }))
vi.mock('@/components/analysis/OpponentAdaptiveShots', () => ({ OpponentAdaptiveShots: () => null }))
vi.mock('@/components/analysis/PreMatchObservationAnalytics', () => ({ PreMatchObservationAnalytics: () => null }))
vi.mock('@/components/analysis/DoublesAnalysis', () => ({ DoublesAnalysis: () => null }))
vi.mock('@/components/analysis/PairPlaystyle', () => ({ PairPlaystyle: () => null }))
vi.mock('@/components/analysis/PairSynergyCard', () => ({ PairSynergyCard: () => null }))
vi.mock('@/components/analysis/WinLossComparison', () => ({ WinLossComparison: () => null }))
vi.mock('@/components/analysis/TournamentComparison', () => ({ TournamentComparison: () => null }))
vi.mock('@/components/common/FilterNotAppliedNote', () => ({ FilterNotAppliedNote: () => null }))
vi.mock('@/components/dashboard/EvidenceBadge', () => ({ EvidenceBadge: () => null, EvidenceLevel: () => null }))
vi.mock('@/components/dashboard/ResearchNotice', () => ({ ResearchNotice: () => null }))
vi.mock('@/components/dashboard/HoldGate', () => ({ HoldGate: () => null }))
vi.mock('@/components/common/MIcon', () => ({ MIcon: () => null }))

import i18n from '@/i18n'
import { DEFAULT_FILTERS } from '@/types'
import { DashboardAdvancedPage } from '../DashboardAdvancedPage'

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <DashboardAdvancedPage playerId={1} filters={DEFAULT_FILTERS} matches={[]} sortedPlayers={[]} />
    </QueryClientProvider>,
  )
}

describe('DashboardAdvancedPage promotion-override access (#700)', () => {
  beforeEach(() => { apiGet.mockReset(); i18n.changeLanguage('ja') })

  it('coach では promotion_overrides を fetch しない', async () => {
    mockRole = 'coach'
    apiGet.mockResolvedValue({ success: true, data: {} })
    wrap()
    await waitFor(() => {})
    const called = apiGet.mock.calls.some((c) => String(c[0]).includes('/analysis/meta/promotion_overrides'))
    expect(called).toBe(false)
  })

  it('analyst では promotion_overrides を fetch する', async () => {
    mockRole = 'analyst'
    apiGet.mockResolvedValue({ success: true, data: {} })
    wrap()
    await waitFor(() => {
      const called = apiGet.mock.calls.some((c) => String(c[0]).includes('/analysis/meta/promotion_overrides'))
      expect(called).toBe(true)
    })
  })

  it('admin で取得失敗時は失敗文言を出す (空一覧に折りたたまない)', async () => {
    mockRole = 'admin'
    apiGet.mockRejectedValue(new Error('403'))
    wrap()
    await waitFor(() => {
      expect(screen.getByText(i18n.t('advanced.override_fetch_failed'))).toBeTruthy()
    })
  })
})
