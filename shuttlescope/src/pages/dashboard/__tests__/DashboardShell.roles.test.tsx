/**
 * DashboardShell のロール別表示 (UI点検 B-52 / B-53)
 * player には生の勝率 KPI と「試合結果」(勝ち/負け) フィルタを出さない。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { UserRole } from '@/types'

let mockRole: UserRole | null = 'player'

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    role: mockRole,
    hasRole: (allowed: UserRole[]) => (!mockRole ? false : mockRole === 'admin' ? true : allowed.includes(mockRole)),
  }),
}))
vi.mock('@/api/client', () => ({
  API_BASE_URL: 'http://x',
  apiGet: vi.fn(async (path: string) => {
    if (path === '/players') {
      return { success: true, data: [{ id: 1, name: '標本 桃子', team: 'DEMO 大学チーム', match_count: 12, is_target: true }] }
    }
    if (path.includes('descriptive')) {
      return {
        success: true,
        data: {
          total_matches: 12, total_rallies: 550, win_rate: 0.538, avg_rally_length: 5,
          end_type_distribution: {}, rally_length_histogram: [], win_by_end_type: {},
          server_win_rate: { as_server: 0.6, as_receiver: 0.5 },
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

async function renderShell() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const utils = render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/dashboard/overview']}>
        <DashboardShell />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  // 選手を選ぶ (KPI / フィルタは選手選択後に出る)
  await waitFor(() => expect(utils.container.querySelector('button')).not.toBeNull())
  fireEvent.click(utils.container.querySelector('[class*="relative"] button') as HTMLElement)
  fireEvent.click(await screen.findByText('標本 桃子'))
  await waitFor(() => expect(utils.container.textContent).toContain('試合数'))
  return utils
}

describe('DashboardShell ロール別表示', () => {
  beforeEach(() => { mockRole = 'player' })

  it('player: 勝率KPIと勝敗フィルタを出さない', async () => {
    const { container } = await renderShell()
    await waitFor(() => expect(container.textContent).toContain('550'))
    expect(container.textContent).not.toContain('53.8%')
    expect(container.textContent).not.toContain('勝率')
    expect(Array.from(container.querySelectorAll('option')).some((o) => o.getAttribute('value') === 'win')).toBe(false)
  })

  it.each(['analyst', 'coach', 'admin'] as UserRole[])('%s: 従来どおり勝率KPIと勝敗フィルタを出す', async (r) => {
    mockRole = r
    const { container } = await renderShell()
    await waitFor(() => expect(container.textContent).toContain('53.8%'))
    expect(Array.from(container.querySelectorAll('option')).some((o) => o.getAttribute('value') === 'win')).toBe(true)
  })
})
