/**
 * 概要画面のロール別表示 (UI点検 B-53 / B-54)
 *
 * 製品ルール: player には個別試合の勝敗 (列・フィルタ・ラベル)、強制/非強制エラー等の
 * 直接的な弱点枠組み、「アナリスト・コーチ向け」と自称するカードを出さない。
 * analyst / coach / admin の表示は従来どおり。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'
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
  apiGet: vi.fn(async (path: string) => {
    if (path.includes('descriptive')) {
      return {
        success: true,
        data: {
          total_matches: 2, total_rallies: 120, win_rate: 0.538, avg_rally_length: 5,
          end_type_distribution: { ace: 3 }, rally_length_histogram: [{ length: 3, count: 4 }],
          win_by_end_type: {}, server_win_rate: { as_server: 0.6, as_receiver: 0.5 },
        },
      }
    }
    return { success: true, data: {} }
  }),
}))

vi.mock('@/components/analysis/ConfidenceCalibration', () => ({ ConfidenceCalibration: () => <div>MOCK_CALIBRATION</div> }))
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

const matches = [
  { match_id: 1, opponent: '相手A', tournament: '大会X', tournament_level: 'IC', date: '2026-01-01', result: 'win', rally_count: 30, format: 'singles', set_count: 2, set_scores: [] },
  { match_id: 2, opponent: '相手B', tournament: '大会Y', tournament_level: 'IS', date: '2026-02-01', result: 'loss', rally_count: 40, format: 'singles', set_count: 2, set_scores: [] },
]
const filters = { result: 'all', tournamentLevel: null, dateFrom: null, dateTo: null } as never

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <DashboardOverviewPage playerId={1} filters={filters} filterApiParams={{}} matches={matches} loadingMatches={false} />
    </QueryClientProvider>,
  )
}

describe('DashboardOverviewPage ロール別表示', () => {
  beforeEach(() => { mockRole = 'player' })

  it('player: 勝敗列・勝敗バッジ・ヒートマップの(勝)(敗)を出さない', () => {
    const { container } = renderPage()
    const text = container.textContent ?? ''
    expect(container.querySelectorAll('thead th')).toHaveLength(5)
    expect(text).not.toMatch(/\(勝\)|\(敗\)/)
    expect(Array.from(container.querySelectorAll('td span')).some((s) => s.textContent === '勝' || s.textContent === '負')).toBe(false)
  })

  it('player: 「アナリスト・コーチ向け」カード・データ品質概況・ラリー終了タイプを出さない', () => {
    const { container } = renderPage()
    const text = container.textContent ?? ''
    expect(text).not.toContain('アナリスト・コーチ向け')
    expect(text).not.toContain('MOCK_CALIBRATION')
    expect(container.querySelector('[data-tutorial="dashboard.quickSummary"]')).toBeNull()
  })

  it.each(['analyst', 'coach', 'admin'] as UserRole[])('%s: 従来どおり勝敗列・データ品質・終了タイプを出す', (r) => {
    mockRole = r
    const { container } = renderPage()
    expect(container.querySelectorAll('thead th')).toHaveLength(6)
    expect(container.textContent).toContain('MOCK_CALIBRATION')
    expect(container.querySelector('[data-tutorial="dashboard.quickSummary"]')).not.toBeNull()
    expect(Array.from(container.querySelectorAll('td span')).some((s) => s.textContent === '勝')).toBe(true)
    expect(container.textContent).toMatch(/\(勝\)/)
  })
})
