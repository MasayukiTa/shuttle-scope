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
    // \u76e3\u67fb #224 \u306e\u5bfe\u8c61\u306f\u300c\u52dd\u7387\u30ab\u30fc\u30c9\u300d\u5358\u4f53\u3002\u753b\u9762\u5168\u4f53\u3067\u306f\u306a\u304f
    // \u52dd\u7387\u30ab\u30fc\u30c9 (\u30e9\u30d9\u30eb=\u30e9\u30ea\u30fc\u52dd\u7387) \u306e\u30b5\u30d6\u30c4\u30ea\u30fc\u5185\u3060\u3051\u3092\u691c\u8a3c\u3059\u308b\u3002
    // (\u5e73\u5747\u30e9\u30ea\u30fc\u9577\u30ab\u30fc\u30c9\u306f\u6b63\u5f53\u306b N=\u2026\u30e9\u30ea\u30fc \u3092\u51fa\u3059\u306e\u3067\u5168\u4f53\u691c\u8a3c\u3060\u3068\u8aa4\u691c\u51fa\u3059\u308b\u3002)
    const winRateCard = (await screen.findByText('\u30e9\u30ea\u30fc\u52dd\u7387')).closest('div.rounded-lg') as HTMLElement
    await waitFor(() => expect(winRateCard.textContent ?? '').toContain('N=53\u8a66\u5408'))
    const cardText = winRateCard.textContent ?? ''
    // \u52dd\u7387\u306e\u6a19\u672c\u306f\u8a66\u5408\u5358\u4f4d
    expect(cardText).toContain('N=53\u8a66\u5408')
    // \u52dd\u7387\u30ab\u30fc\u30c9\u306f N=\u2026\u30e9\u30ea\u30fc \u3068\u3044\u3046\u6a19\u672c\u8868\u8a18\u3092\u51fa\u3055\u306a\u3044
    // (\u30e9\u30d9\u30eb\u300c\u30e9\u30ea\u30fc\u52dd\u7387\u300d\u81ea\u4f53\u306f\u300c\u30e9\u30ea\u30fc\u300d\u3092\u542b\u3080\u305f\u3081 N= \u4ed8\u304d\u306e\u8868\u8a18\u3060\u3051\u3092\u7981\u6b62)
    expect(cardText).not.toContain('N=4,449\u30e9\u30ea\u30fc')
    expect(cardText).not.toMatch(/N=[\d,]+\u30e9\u30ea\u30fc/)
  })
})
