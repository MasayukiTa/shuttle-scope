/**
 * 分析タブの数値・信頼度表示の退行防止テスト (UI点検 B-43 / B-33 / B-34 / B-39 / B-31 / B-26)
 *
 * - 契約キーが backend と一致すること (observed_win_rate / range / player_type 文字列)
 * - 0 件・欠落・NaN を "NaN%" や 0% として描かないこと
 * - 標本数の少ない行に高信頼の★を付けないこと
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('@/api/client', () => ({
  apiGet: vi.fn(),
  API_BASE_URL: '',
}))

vi.mock('@/components/common/RoleGuard', () => ({
  RoleGuard: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

import * as apiClient from '@/api/client'
import { DEFAULT_FILTERS } from '@/types'
import { BayesMatchupCard } from '../BayesMatchupCard'
import { DoublesRoleCard } from '../DoublesRoleCard'
import { RallyLengthWinRate } from '../RallyLengthWinRate'
import { PressurePerformance } from '../PressurePerformance'
import { OpponentStats } from '../OpponentStats'
import { TournamentComparison } from '../TournamentComparison'
import { GrowthJudgmentCard } from '../GrowthJudgmentCard'

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

// recharts の ResponsiveContainer は ResizeObserver を要求する (jsdom には無い)
class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}
;(globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = RO

beforeEach(() => {
  mockApi.mockReset()
})

describe('B-43 BayesMatchupCard', () => {
  const resp = {
    success: true,
    data: {
      global_prior: { alpha: 1, beta: 1 },
      global_win_rate: 0.5,
      total_matches: 3,
      opponent_estimates: [
        {
          opponent_id: 7,
          opponent_name: '標本 桃子',
          n_matches: 2,
          observed_win_rate: 0.5,
          posterior_win_prob: 0.5,
          credible_interval: [0.2, 0.8],
          shrinkage_weight: 0.5,
          opponent_type: 'competitive',
        },
        {
          opponent_id: 8,
          opponent_name: null,
          n_matches: 1,
          observed_win_rate: 1,
          posterior_win_prob: 0.6,
          credible_interval: [0.3, 0.9],
          shrinkage_weight: 0.6,
          opponent_type: 'unknown',
        },
      ],
    },
    meta: { tier: 'research', evidence_level: 'exploratory', sample_size: 3, caution: null },
  }

  it('never renders NaN%, shows names and localized type labels instead of internal keys', async () => {
    mockRoutes({ '/analysis/bayes_matchup': resp })
    const { container } = wrap(<BayesMatchupCard playerId={1} filters={DEFAULT_FILTERS} />)
    await waitFor(() => expect(screen.getAllByText('標本 桃子').length).toBeGreaterThan(0))
    expect(container.textContent).not.toContain('NaN')
    // 内部区分 (unknown/beatable/competitive) がそのまま出ない
    expect(container.textContent).not.toMatch(/\(?(unknown|beatable|competitive|dominating)\)?/)
    // 名前を解決できない相手は「相手不明」
    expect(screen.getAllByText('相手不明').length).toBeGreaterThan(0)
    // 生勝率は backend の observed_win_rate から出る
    expect(container.textContent).toContain('100.0%')
  })
})

describe('B-43 DoublesRoleCard', () => {
  it('shows the insufficient-data message (not NaN%) when the backend has no doubles data', async () => {
    mockRoutes({
      '/analysis/doubles_role': {
        success: true,
        // 旧 backend の応答: ratio キーが欠落していた
        data: { inferred_role: 'unknown', confidence_score: 0.0, total_shots: 0 },
        meta: { sample_size: 0 },
      },
    })
    const { container } = wrap(<DoublesRoleCard playerId={1} filters={DEFAULT_FILTERS} />)
    await waitFor(() => expect(screen.getByText('ダブルスデータが不足しています')).toBeInTheDocument())
    expect(container.textContent).not.toContain('NaN')
  })

  it('does not render NaN% even if ratios are missing while shots > 0', async () => {
    mockRoutes({
      '/analysis/doubles_role': {
        success: true,
        data: { inferred_role: 'front', confidence_score: 0.7, total_shots: 30, phase_breakdown: [], note: null },
        meta: { sample_size: 30 },
      },
    })
    const { container } = wrap(<DoublesRoleCard playerId={1} filters={DEFAULT_FILTERS} />)
    await waitFor(() => expect(container.textContent).toContain('推定ロール'))
    expect(container.textContent).not.toContain('NaN')
  })
})

describe('B-33 RallyLengthWinRate', () => {
  it('shows the insufficient state when no bucket has a label (no unreadable chart)', async () => {
    mockRoutes({
      '/analysis/rally_length_vs_winrate': {
        data: { buckets: [{ count: 5, win_rate: 0.4 }, { count: 0, win_rate: null }], player_type: 'balanced', player_type_ja: 'バランス型' },
        meta: { sample_size: 5, confidence: { level: 'low', stars: '', label: '' } },
      },
    })
    wrap(<RallyLengthWinRate playerId={1} />)
    await waitFor(() => expect(screen.getByText('データ不足（アノテーション後に解析可能）')).toBeInTheDocument())
  })

  it('reads backend range keys and the string player_type', async () => {
    mockRoutes({
      '/analysis/rally_length_vs_winrate': {
        data: {
          buckets: [
            { range: '1-3', count: 10, win_rate: 0.6 },
            { range: '16+', count: 0, win_rate: null },
          ],
          player_type: 'short_game_specialist',
          player_type_ja: '短期決戦型',
        },
        meta: { sample_size: 10, confidence: { level: 'low', stars: '', label: '' } },
      },
    })
    wrap(<RallyLengthWinRate playerId={1} />)
    await waitFor(() => expect(screen.getByText('短期決戦型')).toBeInTheDocument())
  })
})

describe('B-34 PressurePerformance', () => {
  it('shows "データなし" and no red delta for zero-rally segments, and no stars for them', async () => {
    mockRoutes({
      '/analysis/pressure_performance': {
        data: {
          normal: { win_rate: 0.538, rally_count: 550, sample_size: 550 },
          endgame: { win_rate: 0, rally_count: 0, sample_size: 0 },
          deuce: { win_rate: 0, rally_count: 0, sample_size: 0 },
        },
        meta: { sample_size: 550, confidence: { level: 'high', stars: '★★★', label: '' } },
      },
    })
    const { container } = wrap(<PressurePerformance playerId={1} />)
    await waitFor(() => expect(screen.getAllByText('データなし').length).toBeGreaterThanOrEqual(2))
    expect(container.textContent).not.toContain('0.0%')
    expect(container.textContent).not.toContain('−53.8')
    expect(container.textContent).not.toContain('−')
  })
})

describe('B-39 OpponentStats', () => {
  it('derives the star level of each row from its own match count', async () => {
    mockRoutes({
      '/analysis/opponent_stats': {
        success: true,
        data: {
          opponents: [
            { opponent_id: 1, opponent_name: '甲', match_count: 1, win_rate: 1, avg_rally_length: 5, sample_size: 10 },
            { opponent_id: 2, opponent_name: '乙', match_count: 40, win_rate: 0.5, avg_rally_length: 6, sample_size: 400 },
          ],
        },
        meta: { sample_size: 550, confidence: { level: 'high', stars: '★★★', label: '' } },
      },
    })
    const { container } = wrap(<OpponentStats playerId={1} />)
    await waitFor(() => expect(screen.getAllByText('甲').length).toBeGreaterThan(0))
    // 試合数 1 の行: 参考値 (1つ星 = 低) のバッジ。40 試合の行は高信頼
    const titles = Array.from(container.querySelectorAll('button[title]')).map((b) => b.getAttribute('title') ?? '')
    expect(titles.some((t) => t.includes('参考値') && t.includes('1試合'))).toBe(true)
    expect(titles.some((t) => t.includes('高信頼') && t.includes('40試合'))).toBe(true)
    expect(screen.getByText(/試合数が少ない相手の勝率は参考値です/)).toBeInTheDocument()
  })
})

describe('B-31 TournamentComparison', () => {
  it('explains the single-colour bars and carries sample size in labels instead of a colour scale', async () => {
    mockRoutes({
      '/analysis/tournament_level_comparison': {
        success: true,
        data: { levels: [{ level: 'IC', match_count: 1, win_rate: 1, avg_rally_length: 8, sample_size: 30 }] },
        meta: { sample_size: 1, confidence: { level: 'low', stars: '', label: '' } },
      },
    })
    const { container } = wrap(<TournamentComparison playerId={1} />)
    await waitFor(() => expect(screen.getByText(/棒は勝率/)).toBeInTheDocument())
    // 表の大会名セルに coolwarm の赤 (#b40426 系) を使わない
    const firstCell = container.querySelector('tbody td') as HTMLElement
    expect(firstCell.style.color).not.toMatch(/180, ?4, ?38|#b40426/i)
  })
})

describe('B-26 GrowthJudgmentCard', () => {
  it('labels a metric whose window has too little data as undetermined instead of +0.0%', async () => {
    mockRoutes({
      '/analysis/growth_judgment': {
        success: true,
        data: {
          judgment: 'pending',
          judgment_ja: '判定保留',
          metrics: {
            win_rate: { trend: 'improving', delta: 0.048 },
            serve_win_rate: { trend: 'pending', delta: 0 },
          },
          match_count: 12,
          annotated_match_count: 12,
          min_matches_required: 5,
        },
        meta: { sample_size: 12 },
      },
    })
    const { container } = wrap(<GrowthJudgmentCard playerId={1} />)
    await waitFor(() => expect(screen.getByText('判定保留（データ不足）')).toBeInTheDocument())
    expect(container.textContent).not.toContain('+0.0%')
    // 単位はポイント差 (相対変化率の % ではない)
    expect(container.textContent).toContain('+4.8pt')
  })

  it('shows how the trend was computed and how many matches were used or excluded', async () => {
    mockRoutes({
      '/analysis/growth_judgment': {
        success: true,
        data: {
          judgment: 'improving',
          judgment_ja: '改善傾向',
          metrics: {
            win_rate: {
              trend: 'improving',
              delta: 0.037,
              n_matches: 12,
              window: 4,
              early_period: { from: '2025-01-01', to: '2025-01-04' },
              recent_period: { from: '2025-01-09', to: '2025-01-12' },
            },
          },
          match_count: 14,
          annotated_match_count: 12,
          min_matches_required: 5,
          population: { total: 14, used: 12, excluded: { unfinished: 1, zero_rally: 1 } },
        },
        meta: { sample_size: 12 },
      },
    })
    const { container } = wrap(<GrowthJudgmentCard playerId={1} />)
    await waitFor(() => expect(screen.getByTestId('growth-population')).toBeInTheDocument())
    const pop = screen.getByTestId('growth-population').textContent ?? ''
    expect(pop).toContain('14')
    expect(pop).toContain('12')
    expect(container.textContent).toContain('+3.7pt')
    expect(container.textContent).toContain('2025-01-01 ~ 2025-01-04')
    expect(container.textContent).toContain('2025-01-09 ~ 2025-01-12')
  })
})
