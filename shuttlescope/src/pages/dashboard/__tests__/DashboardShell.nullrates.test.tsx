/**
 * DashboardShell KPI: ラリー 0 件の勝率・平均ラリー長は null。「0.0%」「0.0」と描かず「—」にする。
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor, configure } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { UserRole } from '@/types'

// 負荷のある CI / 開発機でも非同期描画の待ちで落ちないよう待ち時間を広げる
configure({ asyncUtilTimeout: 8000 })
vi.setConfig({ testTimeout: 30000 })

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    role: 'analyst',
    hasRole: (allowed: UserRole[]) => allowed.includes('analyst'),
  }),
}))
vi.mock('@/api/client', () => ({
  API_BASE_URL: 'http://x',
  apiGet: vi.fn(async (path: string) => {
    if (path === '/players') {
      return { success: true, data: [{ id: 1, name: '標本 桃子', team: 'DEMO 大学チーム', match_count: 1, is_target: true }] }
    }
    if (path.includes('descriptive')) {
      return {
        success: true,
        data: {
          total_matches: 1, total_rallies: 0, win_rate: null, avg_rally_length: null,
          end_type_distribution: {}, rally_length_histogram: [], win_by_end_type: {},
          server_win_rate: { as_server: null, as_receiver: null, server_count: 0, receiver_count: 0 },
        },
      }
    }
    return { success: true, data: [] }
  }),
}))
vi.mock('@/components/dashboard/DashboardTopNav', () => ({ DashboardTopNav: () => null }))
vi.mock('@/components/common/AdviceStrip', () => ({ AdviceStrip: () => null }))
vi.mock('@/components/tutorial/useTutorial', () => ({ useAutoTutorial: () => {} }))
vi.mock('@/components/common/DateRangeSlider', () => ({ DateRangeSlider: () => null }))
vi.mock('../DashboardOverviewPage', () => ({ DashboardOverviewPage: () => null }))
vi.mock('../DashboardLivePage', () => ({ DashboardLivePage: () => null }))
vi.mock('../DashboardReviewPage', () => ({ DashboardReviewPage: () => null }))
vi.mock('../DashboardGrowthPage', () => ({ DashboardGrowthPage: () => null }))
vi.mock('../DashboardAdvancedPage', () => ({ DashboardAdvancedPage: () => null }))
vi.mock('../DashboardResearchPage', () => ({ DashboardResearchPage: () => null }))

import { DashboardShell } from '../DashboardShell'

Element.prototype.scrollIntoView = () => {}

describe('DashboardShell KPI: 0 件の率は null', () => {
  it('勝率と平均ラリー長を 0.0% / 0.0 ではなく — で出す', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { container } = render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/dashboard/overview']}>
          <DashboardShell />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    await waitFor(() => expect(container.querySelector('button')).not.toBeNull())
    fireEvent.click(container.querySelector('[class*="relative"] button') as HTMLElement)
    fireEvent.click(await screen.findByText('標本 桃子'))
    await waitFor(() => expect(container.textContent).toContain('試合数'))
    await waitFor(() => expect(container.textContent).toContain('勝率'))
    const text = container.textContent ?? ''
    expect(text).not.toMatch(/(^|[^0-9.])0[.]0%/)
    expect(text).not.toContain('NaN')
    expect(text).toContain('—')
  })
})
