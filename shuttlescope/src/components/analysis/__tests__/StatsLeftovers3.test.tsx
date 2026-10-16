/**
 * 統計規則 R1/R4 の消費側テスト (取りこぼし 4 件)。
 *
 * backend が null (データなし / 未算出) で返す項目を、画面が 0% / 50% として描かないこと、
 * 有効データは従来どおり描くことを固定する。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('@/api/client', () => ({
  apiGet: vi.fn(),
  API_BASE_URL: '',
}))

vi.mock('@/components/common/RoleGuard', () => ({
  RoleGuard: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('@/components/common/SearchableSelect', () => ({
  SearchableSelect: () => <select aria-label="select" />,
}))

import * as apiClient from '@/api/client'
import { DEFAULT_FILTERS } from '@/types'
import { AnalystDepthPanel } from '../AnalystDepthPanel'
import { LineupOptimizerPanel } from '../LineupOptimizerPanel'
import { WinLossComparison } from '../WinLossComparison'

const mockApi = vi.mocked(apiClient.apiGet)

function mockRoutes(routes: Record<string, unknown>) {
  mockApi.mockImplementation(async (url: string) => {
    if (url in routes) return routes[url] as never
    return { success: true, data: null, meta: {} } as never
  })
}

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}
;(globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = RO

beforeEach(() => {
  mockApi.mockReset()
})

describe('AnalystDepthPanel: 試合 0 件の予測根拠内訳は 0% / 50% を描かない', () => {
  const depth = (breakdown: unknown) => ({
    success: true,
    data: {
      recent_form: { win_rate: null, sample: 0, trend: null, results: [], overall_wr: null },
      growth_trend: { buckets: [], slope: 0, direction: 'flat', sample: 0 },
      brier_score: { score: null, sample: 0, grade: null },
      nearest_match_evidence: [],
      set_model_type: 'momentum',
      feature_breakdown: breakdown,
      win_prob_v1: null,
      win_prob_v2: null,
    },
  })

  it('shows the insufficient message instead of the breakdown', async () => {
    mockRoutes({
      '/prediction/analyst_depth': depth({
        base_wr: null, recent_wr: null, h2h_wr: null, weights: {},
        obs_modifier: null, raw_blend: null, final: null, insufficient_data: true,
      }),
    })
    const { container } = wrap(<AnalystDepthPanel playerId={1} />)
    await waitFor(() => expect(container.textContent).toContain('試合データがないため予測根拠は算出できません'))
    expect(container.textContent).not.toContain('キャリブレーション済み勝率')
  })

  it('still renders the breakdown for real values', async () => {
    mockRoutes({
      '/prediction/analyst_depth': depth({
        base_wr: 0.6, recent_wr: null, h2h_wr: null, weights: { base: 1 },
        obs_modifier: 0, raw_blend: 0.6, final: 0.6,
      }),
    })
    const { container } = wrap(<AnalystDepthPanel playerId={1} />)
    await waitFor(() => expect(container.textContent).toContain('キャリブレーション済み勝率'))
    expect(container.textContent).not.toContain('試合データがないため予測根拠は算出できません')
  })
})

describe('LineupOptimizerPanel: 勝率 null の選手に % を描かない', () => {
  const players = [
    { id: 1, name: 'HasData' },
    { id: 2, name: 'NoData' },
  ]
  const result = {
    success: true,
    data: {
      ranked_players: [
        { rank: 1, player_id: 1, player_name: 'HasData', win_probability: 0.62, sample_size: 8, h2h_available: false, level_matches_available: false },
        { rank: 2, player_id: 2, player_name: 'NoData', win_probability: null, sample_size: 0, h2h_available: false, level_matches_available: false },
      ],
      opponent_id: null,
      tournament_level: null,
      recommendation: 'HasData',
    },
  }

  async function run(role: 'analyst' | 'coach') {
    mockRoutes({ '/prediction/lineup_optimizer': result })
    const view = wrap(<LineupOptimizerPanel players={players} role={role} />)
    const boxes = screen.getAllByRole('checkbox')
    fireEvent.click(boxes[0])
    fireEvent.click(boxes[1])
    fireEvent.click(screen.getByText('最適化を実行'))
    await waitFor(() => expect(view.container.textContent).toMatch(role === 'analyst' ? /62%/ : /案A/))
    return view
  }

  it('analyst view: only the player with data gets a percentage', async () => {
    const { container } = await run('analyst')
    expect(container.textContent).toContain('62%')
    expect(container.textContent?.match(/\d+%/g)).toEqual(['62%'])
  })

  it('coach view: a player without a win probability is not offered as a candidate', async () => {
    const { container } = await run('coach')
    expect(container.textContent).toContain('案A')
    expect(container.textContent).not.toContain('案B')
  })
})

describe('WinLossComparison: 未算出の ace_rate / error_rate と null のサーブ勝率', () => {
  const stats = (serve: number | null) => ({
    count: 3, avg_rally_length: 4.5, ace_rate: null, error_rate: null,
    serve_win_rate: serve, serve_count: serve == null ? 0 : 10, top_shots: [],
  })

  it('renders a dash (not 0.0%) for a null serve win rate', async () => {
    mockRoutes({
      '/analysis/win_loss_comparison': {
        success: true,
        data: { win_matches: stats(null), loss_matches: stats(null) },
        meta: { sample_size: 6, confidence: { level: 'low', stars: '', label: '' } },
      },
    })
    const { container } = wrap(<WinLossComparison playerId={1} filters={DEFAULT_FILTERS} />)
    await waitFor(() => expect(container.textContent).toContain('サーブ勝率'))
    expect(container.textContent).not.toContain('0.0%')
    expect(container.textContent).not.toContain('NaN')
  })

  it('still renders a numeric serve win rate', async () => {
    mockRoutes({
      '/analysis/win_loss_comparison': {
        success: true,
        data: { win_matches: stats(0.6), loss_matches: stats(0.4) },
        meta: { sample_size: 6, confidence: { level: 'low', stars: '', label: '' } },
      },
    })
    const { container } = wrap(<WinLossComparison playerId={1} filters={DEFAULT_FILTERS} />)
    await waitFor(() => expect(container.textContent).toContain('60.0%'))
    expect(container.textContent).toContain('40.0%')
  })
})
