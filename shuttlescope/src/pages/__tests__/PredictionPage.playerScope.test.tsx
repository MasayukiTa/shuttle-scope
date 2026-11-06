/**
 * PredictionPage: player は本人スコープのみ。ペア/編成/人間予測サブタブを出さない (監査 #502)。
 * 非 player ロール (analyst) では従来どおり全サブタブを表示する。
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'

const roleRef = vi.hoisted(() => ({ value: 'player' as string }))
vi.mock('@/hooks/useAuth', () => ({ useAuth: () => ({ role: roleRef.value }) }))
vi.mock('@tanstack/react-query', () => ({
  useQuery: () => ({ data: { data: [] }, isLoading: false, isError: false, refetch: vi.fn() }),
}))
vi.mock('react-router-dom', () => ({ useSearchParams: () => [new URLSearchParams(), vi.fn()] }))
vi.mock('@/hooks/useBreakpoint', () => ({ useBreakpoint: () => ({ below: () => false }) }))
vi.mock('@/hooks/useCardTheme', () => ({ useCardTheme: () => {} }))
vi.mock('@/utils/analytics', () => ({ analyticsViewLifecycle: () => () => {}, trackAnalysisInteraction: vi.fn() }))
vi.mock('@/utils/downloadReport', () => ({ downloadReport: vi.fn() }))
vi.mock('@/components/analysis/PredictionPanel', () => ({ PredictionPanel: () => null }))
vi.mock('@/components/analysis/PairSimulationPanel', () => ({ PairSimulationPanel: () => null }))
vi.mock('@/components/analysis/LineupOptimizerPanel', () => ({ LineupOptimizerPanel: () => null }))
vi.mock('@/components/analysis/HumanForecastPanel', () => ({ HumanForecastPanel: () => null }))
vi.mock('@/components/analysis/PrematchStatCard', () => ({ PrematchStatCard: () => null }))
vi.mock('@/components/common/AdviceStrip', () => ({ AdviceStrip: () => null }))

import i18n from '@/i18n'
import { PredictionPage } from '../PredictionPage'

afterEach(() => {
  cleanup()
})

describe('PredictionPage player scope (#502)', () => {
  it('player ではペア/編成/人間予測サブタブを表示しない', () => {
    roleRef.value = 'player'
    render(<PredictionPage />)
    expect(screen.queryByText(i18n.t('prediction.pair_simulation'))).toBeNull()
    expect(screen.queryByText(i18n.t('prediction.lineup_optimizer'))).toBeNull()
    expect(screen.queryByText(i18n.t('prediction.human_forecast'))).toBeNull()
  })

  it('analyst では全サブタブを表示する', () => {
    roleRef.value = 'analyst'
    render(<PredictionPage />)
    expect(screen.getAllByText(i18n.t('prediction.pair_simulation')).length).toBeGreaterThan(0)
    expect(screen.getAllByText(i18n.t('prediction.lineup_optimizer')).length).toBeGreaterThan(0)
  })
})
