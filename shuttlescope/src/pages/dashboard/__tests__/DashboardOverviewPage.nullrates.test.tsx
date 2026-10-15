/**
 * 概要画面: サーブ側 / レシーブ側の片側が 0 件のとき、その側の勝率は null (0% ではない)。
 * 側ごとの件数 (server_count / receiver_count) が併記される。
 */
import { describe, it, expect, vi } from 'vitest'
import { render, waitFor, configure } from '@testing-library/react'
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
  apiGet: vi.fn(async (path: string) => {
    if (path.includes('descriptive')) {
      return {
        success: true,
        data: {
          total_matches: 1, total_rallies: 10, win_rate: 0.6, avg_rally_length: 5,
          end_type_distribution: {}, rally_length_histogram: [], win_by_end_type: {},
          server_win_rate: { as_server: 0.6, as_receiver: null, server_count: 10, receiver_count: 0 },
        },
      }
    }
    return { success: true, data: {} }
  }),
}))

vi.mock('@/components/analysis/ConfidenceCalibration', () => ({ ConfidenceCalibration: () => null }))
vi.mock('@/components/analysis/ScoreProgression', () => ({ ScoreProgression: () => null }))
vi.mock('@/components/analysis/IntervalReport', () => ({ IntervalReport: () => null }))
vi.mock('@/components/analysis/SetIntervalSummary', () => ({ SetIntervalSummary: () => null }))
vi.mock('@/components/analysis/CourtHeatModal', () => ({ CourtHeatModal: () => null }))
vi.mock('@/components/court/CourtDiagram', () => ({ CourtDiagram: () => null }))
vi.mock('recharts', () => ({
  BarChart: () => null, Bar: () => null, XAxis: () => null, YAxis: () => null, Tooltip: () => null,
  ResponsiveContainer: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
}))

import { DashboardOverviewPage } from '../DashboardOverviewPage'

const filters = { result: 'all', tournamentLevel: null, dateFrom: null, dateTo: null } as never

describe('DashboardOverviewPage: サーブ/レシーブ勝率', () => {
  it('片側 0 件はその側を「—」にし、件数を併記する (0.0% を出さない)', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { container } = render(
      <QueryClientProvider client={qc}>
        <DashboardOverviewPage playerId={1} filters={filters} filterApiParams={{}} matches={[]} loadingMatches={false} />
      </QueryClientProvider>,
    )
    await waitFor(() => expect(container.textContent).toContain('60.0%'))
    const text = container.textContent ?? ''
    expect(text).not.toMatch(/(^|[^0-9.])0[.]0%/)
    expect(text).not.toContain('NaN')
    expect(text).toContain('—')
    expect(text).toContain('10ラリー')
    expect(text).toContain('0ラリー')
  })
})
