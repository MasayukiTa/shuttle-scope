/**
 * 監査 #224: 主解析ダッシュボードの「勝率」KPI は標本単位を試合にする。
 *
 * 以前は勝率 52.4% の直下に N=4,449ラリー と出していた。勝率の標本単位は試合
 * (ここでは 53 試合) なので、ラリー数 N を流用すると確からしさを過大表示する。
 * 勝率カードは N=53試合 を出し、N=…ラリー を出さないことを固定する。
 * (ラリー由来の平均ラリー長カードは従来どおり N=…ラリー のまま。)
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor, configure } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { UserRole } from '@/types'

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
      return { success: true, data: [{ id: 1, name: '\u6a19\u672c \u6843\u5b50', team: 'DEMO', match_count: 53, is_target: true }] }
    }
    if (path.includes('descriptive')) {
      return {
        success: true,
        data: {
          total_matches: 53, total_rallies: 4449, win_rate: 0.524, avg_rally_length: 8.2,
          end_type_distribution: {}, rally_length_histogram: [], win_by_end_type: {},
          server_win_rate: { as_server: 0.5, as_receiver: 0.5, server_count: 10, receiver_count: 10 },
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

class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}
;(globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = RO

describe('DashboardShell KPI: \u52dd\u7387\u306e\u6a19\u672c\u5358\u4f4d\u306f\u8a66\u5408 (#224)', () => {
  it('\u52dd\u7387\u30ab\u30fc\u30c9\u306f N=53\u8a66\u5408 \u3092\u51fa\u3057 N=4,449\u30e9\u30ea\u30fc \u3092\u51fa\u3055\u306a\u3044', async () => {
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
    fireEvent.click(await screen.findByText('\u6a19\u672c \u6843\u5b50'))
    await waitFor(() => expect(container.textContent).toContain('\u52dd\u7387'))
    const text = container.textContent ?? ''
    // \u52dd\u7387\u306e\u6a19\u672c\u306f\u8a66\u5408\u5358\u4f4d
    expect(text).toContain('N=53\u8a66\u5408')
    // \u52dd\u7387\u306e\u4e0b\u306b\u30e9\u30ea\u30fc\u6570 4,449 \u3092\u6d41\u7528\u3057\u306a\u3044
    expect(text).not.toContain('N=4,449\u30e9\u30ea\u30fc')
  })
})
