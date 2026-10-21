/**
 * 勝率の「参考値」表示 (C1 / C2 / C3) の消費側テスト。
 *
 * - 最終勝率は win_probability の 1 つだけを読む (要約帯・大きい数字・展開パターン)
 * - 試合数が最小標本未満 (backend の win_probability_reference.is_reference) なら
 *   「参考値（n試合）」と理由を出す。最小標本以上なら出さない
 * - Brier が基準 (0.25) より悪いときは、コイントス基準以下であることを文で言う
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('@/api/client', () => ({
  apiGet: vi.fn(),
  API_BASE_URL: '',
}))

vi.mock('@/components/common/RoleGuard', () => ({
  RoleGuard: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ role: 'analyst' }),
}))

import * as apiClient from '@/api/client'
import { PredictionPanel } from '../PredictionPanel'

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

const MIN_SAMPLE = 5

type Reference = { is_reference: boolean; reason: 'sample' | 'brier' | null; min_sample: number; sample_size: number }

const previewData = (n: number, reference: Reference, extra: Record<string, unknown> = {}) => ({
  win_probability: 0.61,
  win_probability_ci: null,
  win_probability_reference: reference,
  h2h_win_rate: 0.67,
  h2h_n: 3,
  sample_size: n,
  similar_matches: 0,
  set_distribution: { '2-0': 0.3, '2-1': 0.3, '1-2': 0.2, '0-2': 0.2 },
  score_bands: {},
  feature_breakdown: { base_wr: 0.5, recent_wr: 0.5, h2h_wr: 0.67, weights: { base: 1 }, obs_modifier: 0, raw_blend: 0.61, final: 0.61 },
  recent_form: { win_rate: 0.5, sample: n, trend: null, results: [], overall_wr: 0.5 },
  set_model_type: 'momentum',
  score_volatility: { volatility_score: 0.3, close_match_rate: 0.3, dominant_match_rate: 0.3, typical_margin: 5, sample: n },
  calibrated_scorelines: [],
  most_likely_scorelines: [],
  confidence: 0.3,
  observation_context: {},
  tactical_notes: [],
  caution_flags: [],
  prediction_drivers: { primary_type: 'all', primary_count: n, h2h_count: 3, same_level_count: 0, all_count: n, has_observations: false, drivers: [] },
  ...extra,
})

function renderPanel(data: unknown, n: number) {
  mockRoutes({
    '/prediction/match_preview': {
      success: true,
      data,
      meta: { sample_size: n, confidence: { level: 'low', stars: '★☆☆', label: '' } },
    },
  })
  return wrap(
    <PredictionPanel playerId={1} playerName="甲" players={[]} opponentId={2} tournamentLevel="" />,
  )
}

describe('PredictionPanel: 勝率の参考値表示', () => {
  it('labels the win probability as a reference value with n below the minimum sample', async () => {
    const n = MIN_SAMPLE - 2
    const { container } = renderPanel(
      previewData(n, { is_reference: true, reason: 'sample', min_sample: MIN_SAMPLE, sample_size: n }),
      n,
    )
    await waitFor(() => expect(container.textContent).toContain(`参考値（${n}試合）`))
    expect(container.textContent).toContain(`${MIN_SAMPLE}試合に満たない`)
    // 最終勝率 61% は 1 つの値から描く。直接対戦値 67% は勝率として描かない
    expect(container.textContent).toContain('61%')
    expect(container.textContent).not.toContain('67%')
  })

  it('does not show the reference wording at or above the minimum sample', async () => {
    const n = MIN_SAMPLE + 3
    const { container } = renderPanel(
      previewData(n, { is_reference: false, reason: null, min_sample: MIN_SAMPLE, sample_size: n }),
      n,
    )
    await waitFor(() => expect(container.textContent).toContain('61%'))
    expect(container.textContent).not.toContain('参考値（')
    expect(container.textContent).not.toContain('に満たない')
  })

  it('says the model is no better than the coin-toss baseline when Brier is poor', async () => {
    const n = MIN_SAMPLE + 5
    const { container } = renderPanel(
      previewData(
        n,
        { is_reference: true, reason: 'brier', min_sample: MIN_SAMPLE, sample_size: n },
        { brier_score: { score: 0.256, sample: n, grade: 'poor' } },
      ),
      n,
    )
    await waitFor(() => expect(container.textContent).toContain(`参考値（${n}試合）`))
    expect(container.textContent).toContain('コイントス')
    expect(container.textContent).toContain('0.256')
  })
})
