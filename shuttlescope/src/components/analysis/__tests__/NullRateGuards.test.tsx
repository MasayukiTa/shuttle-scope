/**
 * 統計ルール (2026-10-15): 分母 0 の率は backend が null で返す。
 * 画面は null を 0% / NaN% / 負の差分として描かず、「—」「データなし」「参考値」にする。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, configure } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

// 負荷のある CI / 開発機でも非同期描画の待ちで落ちないよう待ち時間を広げる
configure({ asyncUtilTimeout: 8000 })
vi.setConfig({ testTimeout: 30000 })

vi.mock('@/api/client', () => ({
  apiGet: vi.fn(),
  API_BASE_URL: '',
}))

vi.mock('@/components/common/RoleGuard', () => ({
  RoleGuard: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

import * as apiClient from '@/api/client'
import { RallyLengthWinRate } from '../RallyLengthWinRate'
import { PostLongRallyStats } from '../PostLongRallyStats'
import { TemporalPerformance } from '../TemporalPerformance'
import { OpponentStats } from '../OpponentStats'
import { TournamentComparison } from '../TournamentComparison'
import { DoublesAnalysis } from '../DoublesAnalysis'
import { HazardFatigueCard } from '../HazardFatigueCard'
import { AnalystDepthPanel } from '../AnalystDepthPanel'
import { DEFAULT_FILTERS } from '@/types'

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

describe('RallyLengthWinRate: player type withheld on a small sample', () => {
  it('shows the pending note instead of a type badge', async () => {
    mockRoutes({
      '/analysis/rally_length_vs_winrate': {
        data: {
          buckets: [{ range: '1-3', count: 1, win_rate: 1 }, { range: '16+', count: 0, win_rate: null }],
          player_type: 'unknown',
          player_type_ja: '不明',
          insufficient_data: true,
        },
        meta: { sample_size: 1, confidence: { level: 'low', stars: '', label: '' } },
      },
    })
    wrap(<RallyLengthWinRate playerId={1} />)
    await waitFor(() => expect(screen.getByText('タイプ判定は標本不足のため保留')).toBeInTheDocument())
    expect(screen.queryByText('短期決戦型')).toBeNull()
  })
})

describe('PostLongRallyStats: a side with no rallies is null, not 0%', () => {
  it('renders — and no fake negative difference', async () => {
    mockRoutes({
      '/analysis/post_long_rally_stats': {
        success: true,
        data: {
          normal: { win_rate: 0.5, avg_rally_length: 5, count: 12 },
          post_long: { win_rate: null, avg_rally_length: null, count: 0 },
          diff_win_rate: null,
        },
        meta: { sample_size: 12, confidence: { level: 'medium', stars: '', label: '' } },
      },
    })
    const { container } = wrap(<PostLongRallyStats playerId={1} />)
    await waitFor(() => expect(container.textContent).toContain('50.0%'))
    expect(container.textContent).not.toContain('NaN')
    expect(container.textContent).not.toContain('-50.0%')
    expect(container.textContent).not.toMatch(/(^|[^0-9.])0[.]0%/)
    expect(container.textContent).toContain('—')
  })
})

describe('TemporalPerformance: empty phase is null', () => {
  it('does not print 0.0% for a phase without rallies', async () => {
    mockRoutes({
      '/analysis/temporal_performance': {
        success: true,
        data: {
          phases: [
            { phase: '序盤(0-7点)', win_rate: 0.5, rally_count: 8 },
            { phase: '中盤(8-14点)', win_rate: null, rally_count: 0 },
          ],
        },
        meta: { sample_size: 8, confidence: { level: 'low', stars: '', label: '' } },
      },
    })
    const { container } = wrap(<TemporalPerformance playerId={1} />)
    await waitFor(() => expect(container.textContent).toContain('50.0%'))
    expect(container.textContent).not.toMatch(/(^|[^0-9.])0[.]0%/)
    expect(container.textContent).not.toContain('NaN')
    expect(container.textContent).toContain('—')
  })
})

describe('OpponentStats: insufficient rows are greyed even without the old match-count fallback', () => {
  it('uses the backend insufficient marker and tolerates a null average rally length', async () => {
    mockRoutes({
      '/analysis/opponent_stats': {
        success: true,
        data: {
          opponents: [
            { opponent_id: 1, opponent_name: '甲', match_count: 5, win_rate: 1, avg_rally_length: null, sample_size: 0, insufficient: true },
          ],
        },
        meta: { sample_size: 0, confidence: { level: 'low', stars: '', label: '' } },
      },
    })
    const { container } = wrap(<OpponentStats playerId={1} />)
    await waitFor(() => expect(screen.getAllByText('甲').length).toBeGreaterThan(0))
    expect(container.textContent).not.toContain('NaN')
    // 勝率セルは強調色 (text-blue-300) ではなく灰色
    const rateCell = container.querySelector('td span.num-cell.text-gray-400') as HTMLElement | null
    expect(rateCell).not.toBeNull()
    expect(rateCell?.textContent).toBe('100.0%')
    expect(container.querySelector('td span.text-blue-300')).toBeNull()
  })
})

describe('TournamentComparison: low-sample levels are greyed with a hint', () => {
  it('shows the hint and tolerates null avg rally length', async () => {
    mockRoutes({
      '/analysis/tournament_level_comparison': {
        success: true,
        data: {
          levels: [
            { level: 'IC', match_count: 2, win_rate: 1, avg_rally_length: null, sample_size: 0, insufficient: true },
            { level: 'SJL', match_count: 6, win_rate: 0.5, avg_rally_length: 7, sample_size: 300, insufficient: false },
          ],
        },
        meta: { sample_size: 8, confidence: { level: 'low', stars: '', label: '' } },
      },
    })
    const { container } = wrap(<TournamentComparison playerId={1} />)
    await waitFor(() => expect(screen.getByText(/試合数が少ない大会レベルの勝率は参考値です/)).toBeInTheDocument())
    expect(container.textContent).not.toContain('NaN')
    const cells = Array.from(container.querySelectorAll('tbody tr')).map((tr) => tr.textContent ?? '')
    expect(cells[0]).toContain('100.0%')
    expect(cells[0]).toContain('—')
    expect(cells[1]).toContain('7.0')
  })
})

describe('DoublesAnalysis: sides with no rallies are null', () => {
  it('shows — instead of a 0% balance meter when there is no stroke-sharing data', async () => {
    mockRoutes({
      '/analysis/stroke_sharing': {
        success: true,
        data: {
          balanced_win_rate: null,
          imbalanced_win_rate: null,
          balanced_count: 0,
          imbalanced_count: 0,
          avg_balance_ratio: null,
        },
        meta: { sample_size: 5, confidence: { level: 'low', stars: '', label: '' } },
      },
    })
    const { container } = wrap(<DoublesAnalysis playerId={1} allMatches={[]} />)
    await waitFor(() => expect(container.querySelector('span.drop-shadow')).not.toBeNull())
    expect(container.querySelector('span.drop-shadow')?.textContent).toBe('—')
    expect(container.textContent).not.toContain('NaN')
  })

  it('does not draw 0% for the empty serve/receive side', async () => {
    mockRoutes({
      '/analysis/doubles_serve_receive': {
        success: true,
        data: {
          serve_win_rate: 0.6,
          receive_win_rate: null,
          serve_count: 10,
          receive_count: 0,
          serve_style: {},
          receive_zones: [],
        },
        meta: { sample_size: 10, confidence: { level: 'low', stars: '', label: '' } },
      },
    })
    const { container } = wrap(<DoublesAnalysis playerId={1} allMatches={[]} />)
    await waitFor(() => expect(container.textContent).toContain('サーブ'))
    expect(container.textContent).not.toContain('NaN')
    expect(container.textContent).not.toContain('Infinity')
  })
})

describe('HazardFatigueCard: no observation for after-long / endgame is null', () => {
  it('shows — instead of a 0.5-derived percentage or a green low-risk colour', async () => {
    mockRoutes({
      '/analysis/hazard_fatigue': {
        success: true,
        data: {
          hazard_next_loss: 0.4,
          hazard_after_long: null,
          hazard_endgame: null,
          combined_hazard: 0.45,
          collapse_risk_band: 'moderate',
          calibrated_confidence: 0.2,
          baseline_loss_rate: 0.5,
          total_rallies: 6,
          after_long_rally: { n_long_rallies: 0, n_loss_after_long: 0, loss_rate: null, vs_baseline: null },
          endgame_analysis: { n_endgame: 0, n_loss_endgame: 0, loss_rate: null, vs_baseline: null },
          window_trend: [],
        },
        meta: { tier: 'research', evidence_level: 'exploratory', sample_size: 6, caution: null },
      },
    })
    const { container } = wrap(<HazardFatigueCard playerId={1} filters={DEFAULT_FILTERS} />)
    await waitFor(() => expect(container.textContent).toContain('40.0%'))
    expect(container.textContent).not.toContain('NaN')
    // after_long / endgame の 2 つは「—」で、低リスクを意味する緑色にもしない
    const cells = Array.from(container.querySelectorAll('p.text-sm.font-semibold'))
    expect(cells.map((p) => p.textContent)).toEqual(['40.0%', '—', '—'])
    expect(cells[1].className).not.toContain('emerald')
    expect(cells[2].className).not.toContain('emerald')
  })
})

describe('AnalystDepthPanel recent form: no matches is not a 50% / stable trend', () => {
  it('shows — for the recent form and omits the recent row of the breakdown', async () => {
    mockRoutes({
      '/prediction/analyst_depth': {
        success: true,
        data: {
          recent_form: { win_rate: null, sample: 0, trend: null, results: [], overall_wr: null },
          growth_trend: { buckets: [], slope: 0, direction: 'flat', sample: 0 },
          brier_score: { score: null, sample: 0, grade: null },
          nearest_match_evidence: [],
          set_model_type: 'momentum',
          feature_breakdown: {
            base_wr: 0.5, recent_wr: null, h2h_wr: null, weights: { base: 1 },
            obs_modifier: 0, raw_blend: 0.5, final: 0.5,
          },
          win_prob_v1: 0.5,
          win_prob_v2: 0.5,
        },
      },
    })
    const { container } = wrap(<AnalystDepthPanel playerId={1} />)
    await waitFor(() => expect(container.textContent).toContain('—'))
    expect(container.textContent).not.toContain('NaN')
    // 直近勝率 0% / 全体 0% の偽表示が出ない
    expect(container.textContent).not.toContain('直近勝率')
    expect(container.textContent).not.toContain('全体 0%')
    expect(container.textContent).not.toContain('直近0試合')
  })
})
