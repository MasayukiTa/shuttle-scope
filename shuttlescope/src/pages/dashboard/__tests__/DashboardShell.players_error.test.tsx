/**
 * 監査 #650: DashboardShell の選手一覧 (GET /players) 取得失敗を
 * 「未選択」に変換せず、明示的なエラー状態 (再試行付き) を出す。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { UserRole } from '@/types'

let mockRole: UserRole | null = 'analyst'
let playersShouldFail = true

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
      if (playersShouldFail) throw new Error('network down')
      return { success: true, data: [{ id: 1, name: '標本 桃子', team: 'DEMO', match_count: 12, is_target: true }] }
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

function renderShell(entry = '/dashboard/overview') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/dashboard/*" element={<DashboardShell />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('DashboardShell 選手一覧取得失敗', () => {
  beforeEach(() => { mockRole = 'analyst'; playersShouldFail = true })

  it('取得失敗時は「未選択」ではなく明示的なエラーを出す', async () => {
    const { container } = renderShell()
    await waitFor(() => expect(container.querySelector('[role="alert"]')).not.toBeNull())
    expect(container.textContent).not.toContain('選手を選択してください')
    expect(screen.getByText('再試行')).toBeTruthy()
  })

  it('成功時は通常の未選択状態を出す', async () => {
    playersShouldFail = false
    const { container } = renderShell()
    await waitFor(() => expect(container.textContent).toContain('選手を選択してください'))
    expect(container.querySelector('[role="alert"]')).toBeNull()
  })
})
