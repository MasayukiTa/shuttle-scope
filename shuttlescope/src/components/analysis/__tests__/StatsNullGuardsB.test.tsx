/**
 * 統計規則 R1/R4 (n=0 は null、画面は 0% / 50% を描かない) の消費側テスト — 担当 B 群。
 *
 * backend が rate を null で返すようになった項目について、画面が
 *   - null を 0% / 50% / NaN として描かない
 *   - 有効データは従来どおり描く
 * ことを固定する。
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

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ role: 'analyst' }),
}))

// SearchableSelect は素朴な <select> に置き換える (選手選択だけが目的)
vi.mock('@/components/common/SearchableSelect', () => ({
  SearchableSelect: ({
    options,
    value,
    onChange,
    placeholder,
  }: {
    options: { value: number; label: string }[]
    value: number | null
    onChange: (v: number | null) => void
    placeholder?: string
  }) => (
    <select
      aria-label={placeholder ?? 'select'}
      value={value ?? ''}
      onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
    >
      <option value="" />
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  ),
}))

import * as apiClient from '@/api/client'
import { DEFAULT_FILTERS } from '@/types'
import { BayesMatchupCard } from '../BayesMatchupCard'
import { DoublesRoleCard } from '../DoublesRoleCard'
import { PairSynergyCard } from '../PairSynergyCard'
import { PairCombinedView } from '../PairCombinedView'
import { PairSimulationPanel } from '../PairSimulationPanel'
import { PredictionPanel } from '../PredictionPanel'
import { AnalystDepthPanel } from '../AnalystDepthPanel'

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

describe('BayesMatchupCard: global_win_rate が null のとき 0% を描かない', () => {
  const est = {
    opponent_id: 7,
    opponent_name: '標本 桃子',
    n_matches: 2,
    observed_win_rate: 0.5,
    posterior_win_prob: 0.5,
    credible_interval: [0.2, 0.8],
    shrinkage_weight: 0.5,
    opponent_type: 'competitive',
  }

  it('renders a dash for a null global win rate', async () => {
    mockRoutes({
      '/analysis/bayes_matchup': {
        success: true,
        data: { global_prior: { alpha: 1, beta: 1 }, global_win_rate: null, total_matches: 2, opponent_estimates: [est] },
        meta: { tier: 'research', evidence_level: 'exploratory', sample_size: 2, caution: null },
      },
    })
    const { container } = wrap(<BayesMatchupCard playerId={1} filters={DEFAULT_FILTERS} />)
    await waitFor(() => expect(container.textContent).toContain('全体勝率: —'))
    expect(container.textContent).not.toContain('全体勝率: 0.0%')
  })

  it('still renders a numeric global win rate', async () => {
    mockRoutes({
      '/analysis/bayes_matchup': {
        success: true,
        data: { global_prior: { alpha: 1, beta: 1 }, global_win_rate: 0.5, total_matches: 2, opponent_estimates: [est] },
        meta: { tier: 'research', evidence_level: 'exploratory', sample_size: 2, caution: null },
      },
    })
    const { container } = wrap(<BayesMatchupCard playerId={1} filters={DEFAULT_FILTERS} />)
    await waitFor(() => expect(container.textContent).toContain('全体勝率: 50.0%'))
  })
})

describe('DoublesRoleCard: null ratio / null confidence は「データ不足」', () => {
  it('shows the insufficient message and no NaN / 0% when everything is null', async () => {
    mockRoutes({
      '/analysis/doubles_role': {
        success: true,
        data: {
          inferred_role: 'unknown',
          confidence_score: null,
          front_ratio: null,
          back_ratio: null,
          neutral_ratio: null,
          total_shots: 0,
          phase_breakdown: [],
          note: null,
        },
        meta: { sample_size: 0 },
      },
    })
    const { container } = wrap(<DoublesRoleCard playerId={1} filters={DEFAULT_FILTERS} />)
    await waitFor(() => expect(screen.getByText('ダブルスデータが不足しています')).toBeInTheDocument())
    expect(container.textContent).not.toContain('NaN')
    expect(container.textContent).not.toContain('0.0%')
  })
})

describe('PairSynergyCard: null の平均ラリー長 / 打球分担を 0 として描かない', () => {
  const base = {
    success: true,
    meta: { sample_size: 1, confidence: { level: 'low', stars: '', label: '' } },
  }

  it('hides rally-length and stroke-share when they are null', async () => {
    mockRoutes({
      '/analysis/pair_synergy': {
        ...base,
        data: {
          player_avg_win_rate: 1,
          pairs: [{
            partner_id: 2, partner_name: 'P', match_count: 1, win_rate: 1, synergy_score: 0,
            avg_rally_length: null, stroke_share: null,
          }],
        },
      },
    })
    const { container } = wrap(<PairSynergyCard playerId={1} />)
    await waitFor(() => expect(screen.getByText('P')).toBeInTheDocument())
    expect(container.textContent).not.toContain('平均ラリー長')
    expect(container.textContent).not.toContain('打球分担')
    expect(container.textContent).not.toContain('NaN')
  })

  it('shows them when present', async () => {
    mockRoutes({
      '/analysis/pair_synergy': {
        ...base,
        data: {
          player_avg_win_rate: 0.5,
          pairs: [{
            partner_id: 2, partner_name: 'P', match_count: 4, win_rate: 0.75, synergy_score: 0.25,
            avg_rally_length: 6.5, stroke_share: 0.55,
          }],
        },
      },
    })
    const { container } = wrap(<PairSynergyCard playerId={1} />)
    await waitFor(() => expect(container.textContent).toContain('平均ラリー長: 6.5球'))
    expect(container.textContent).toContain('打球分担: 55%')
    expect(container.textContent).toContain('全試合平均勝率:')
  })

  it('does not render 0% for a null player average (pairs empty → no-data path, no crash)', async () => {
    mockRoutes({
      '/analysis/pair_synergy': { ...base, data: { player_avg_win_rate: null, pairs: [] }, meta: { sample_size: 0 } },
    })
    const { container } = wrap(<PairSynergyCard playerId={1} />)
    await waitFor(() => expect(container.textContent).toContain('ペアシナジースコア'))
    expect(container.textContent).not.toContain('NaN')
  })
})

describe('PairCombinedView: ストローク 0 件の分担比率は描かない', () => {
  const meta = { sample_size: 5, confidence: { level: 'low', stars: '', label: '' } }

  it('omits the stroke-share block for null shares', async () => {
    mockRoutes({
      '/analysis/pair_combined': {
        success: true,
        data: {
          pair_win_rate: 1, pair_match_count: 1, shared_matches: [1],
          stroke_share: { player_a: null, player_b: null },
          common_loss_pattern: null, common_win_shot: null,
        },
        meta,
      },
    })
    const { container } = wrap(<PairCombinedView playerAId={1} playerBId={2} />)
    await waitFor(() => expect(container.textContent).toContain('100%'))
    expect(container.textContent).not.toContain('NaN')
    expect(container.textContent).not.toContain('0%0%')
    expect(container.querySelectorAll('div.rounded-full.h-2').length).toBe(0)
  })

  it('draws the stroke-share bar when shares exist', async () => {
    mockRoutes({
      '/analysis/pair_combined': {
        success: true,
        data: {
          pair_win_rate: 1, pair_match_count: 1, shared_matches: [1],
          stroke_share: { player_a: 0.6, player_b: 0.4 },
          common_loss_pattern: null, common_win_shot: null,
        },
        meta,
      },
    })
    const { container } = wrap(<PairCombinedView playerAId={1} playerBId={2} />)
    await waitFor(() => expect(container.textContent).toContain('60%'))
    expect(container.textContent).toContain('40%')
  })
})

describe('PairSimulationPanel: 実績 0 件のペアに 50% を描かない', () => {
  const players = [{ id: 1, name: '選手甲' }, { id: 2, name: '選手乙' }]

  async function runSimulation() {
    wrap(<PairSimulationPanel players={players} />)
    const selects = screen.getAllByRole('combobox')
    fireEvent.change(selects[0], { target: { value: '1' } })
    fireEvent.change(screen.getAllByRole('combobox')[1], { target: { value: '2' } })
    fireEvent.click(screen.getByText('シミュレーション実行'))
  }

  it('shows the no-record message when win_probability is null', async () => {
    mockRoutes({
      '/prediction/pair_simulation': {
        success: true,
        data: {
          pair_name: '甲 / 乙', win_probability: null,
          set_distribution: { '2-0': 0, '2-1': 0, '1-2': 0, '0-2': 0 },
          pair_strengths: [], pair_cautions: ['ペアとしての対戦データなし — 個人成績から予測できません'],
          confidence: 0, sample_size: 0,
        },
        meta: { sample_size: 0, confidence: { level: 'low', stars: '★☆☆', label: '参考値' } },
      },
    })
    await runSimulation()
    await waitFor(() => expect(screen.getByText('ペアとしての対戦実績がないため、勝率は算出していません')).toBeInTheDocument())
    expect(document.body.textContent).not.toContain('50%')
    expect(document.body.textContent).not.toContain('NaN')
  })

  it('shows the percentage when there is a record', async () => {
    mockRoutes({
      '/prediction/pair_simulation': {
        success: true,
        data: {
          pair_name: '甲 / 乙', win_probability: 0.667,
          set_distribution: { '2-0': 0.4, '2-1': 0.3, '1-2': 0.2, '0-2': 0.1 },
          pair_strengths: [], pair_cautions: [], confidence: 0.4, sample_size: 1,
        },
        meta: { sample_size: 1, confidence: { level: 'low', stars: '★☆☆', label: '参考値' } },
      },
    })
    await runSimulation()
    await waitFor(() => expect(document.body.textContent).toContain('67%'))
  })

  it('ranks only partners that have a record; null-probability partners go to the no-record list', async () => {
    mockRoutes({
      '/prediction/pair_ranking': {
        success: true,
        data: {
          anchor_player: { id: 1, name: '選手甲' },
          tournament_level: null,
          ranked_partners: [
            { rank: 1, partner_id: 2, partner_name: '実績あり', partner_team: null, win_probability: 0.667, sample_size: 1, confidence: 0.3, confidence_meta: { level: 'low', stars: '', label: '' } },
            { rank: 2, partner_id: 3, partner_name: '実績なし', partner_team: null, win_probability: null, sample_size: 0, confidence: 0, confidence_meta: { level: 'low', stars: '', label: '' } },
          ],
        },
      },
    })
    wrap(<PairSimulationPanel players={players} />)
    // ランキング節の選手選択 (3 番目の select は大会レベルなので、anchor は 3 つ目の combobox 群の先頭)
    const boxes = screen.getAllByRole('combobox')
    fireEvent.change(boxes[boxes.length - 2], { target: { value: '1' } })
    fireEvent.click(screen.getByText('ランキング算出'))
    await waitFor(() => expect(screen.getByText('実績あり')).toBeInTheDocument())
    expect(document.body.textContent).toContain('67%')
    expect(document.body.textContent).not.toContain('NaN')
  })
})

describe('PredictionPanel: 試合 0 件 (win_probability null) は数値でなくデータ不足', () => {
  // 旧実装でも描画が落ちない完全なペイロード (win_probability だけ null)。
  // 不完全なデータだと旧実装は例外で空描画になり、テストが空振りする。
  const previewData = (n: number) => ({
    win_probability: null,
    win_probability_v2: null,
    sample_size: n,
    similar_matches: 0,
    set_distribution: { '2-0': 0.25, '2-1': 0.25, '1-2': 0.25, '0-2': 0.25 },
    score_bands: {},
    feature_breakdown: { base_wr: 0.5, recent_wr: 0.5, h2h_wr: null, weights: { base: 1 }, obs_modifier: 0, raw_blend: 0.5, final: 0.5 },
    recent_form: { win_rate: 0.5, sample: n, trend: 'stable', results: [], overall_wr: 0.5 },
    set_model_type: 'momentum',
    score_volatility: { volatility_score: 0.3, close_match_rate: 0.3, dominant_match_rate: 0.3, typical_margin: 5, sample: n },
    calibrated_scorelines: [],
    most_likely_scorelines: [],
    confidence: 0.3,
    observation_context: {},
    tactical_notes: [],
    caution_flags: [],
    prediction_drivers: { primary_type: 'all', primary_count: n, h2h_count: 0, same_level_count: 0, all_count: n, has_observations: false, drivers: [] },
  })

  it('does not render a win percentage when win_probability is null', async () => {
    mockRoutes({
      '/prediction/match_preview': {
        success: true,
        data: previewData(0),
        meta: { sample_size: 0, confidence: { level: 'low', stars: '', label: '' } },
      },
    })
    const { container } = wrap(
      <PredictionPanel playerId={1} playerName="甲" players={[]} opponentId={2} tournamentLevel="" />,
    )
    await waitFor(() => expect(mockApi).toHaveBeenCalled())
    // 0% / 50% / NaN を勝率として描かない
    await new Promise((r) => setTimeout(r, 400))
    expect(container.textContent).not.toMatch(/(^|[^\d])(0|50)%/)
    expect(container.textContent).not.toContain('NaN')
  })

  it('guards a null win_probability even if sample_size is positive', async () => {
    mockRoutes({
      '/prediction/match_preview': {
        success: true,
        data: previewData(3),
        meta: { sample_size: 3, confidence: { level: 'low', stars: '', label: '' } },
      },
    })
    const { container } = wrap(
      <PredictionPanel playerId={1} playerName="甲" players={[]} opponentId={2} tournamentLevel="" />,
    )
    await waitFor(() => expect(mockApi).toHaveBeenCalled())
    await new Promise((r) => setTimeout(r, 400))
    expect(container.textContent).not.toMatch(/(^|[^\d])0%/)
    expect(container.textContent).not.toContain('NaN')
  })
})

describe('AnalystDepthPanel: null の v1/v2 勝率でキャリブレーション行を出さない', () => {
  const depth = (v1: number | null, v2: number | null) => ({
    success: true,
    data: {
      recent_form: { win_rate: 0.5, sample: 5, trend: 'stable', results: ['W', 'L'], overall_wr: 0.5 },
      growth_trend: { buckets: [], slope: 0, direction: 'flat', sample: 0 },
      brier_score: { score: null, sample: 0, grade: null },
      nearest_match_evidence: [],
      set_model_type: 'momentum',
      feature_breakdown: { base_wr: 0.5, recent_wr: 0.5, h2h_wr: null, weights: { base: 1 }, obs_modifier: 0, raw_blend: 0.5, final: 0.5 },
      win_prob_v1: v1,
      win_prob_v2: v2,
    },
  })

  it('omits the calibration line when either value is null', async () => {
    mockRoutes({ '/prediction/analyst_depth': depth(null, null) })
    const { container } = wrap(<AnalystDepthPanel playerId={1} />)
    await waitFor(() => expect(container.textContent).toContain('セットモデル'))
    expect(container.textContent).not.toContain('v1勝率')
  })

  it('shows the calibration line for real values', async () => {
    mockRoutes({ '/prediction/analyst_depth': depth(0.6, 0.55) })
    const { container } = wrap(<AnalystDepthPanel playerId={1} />)
    await waitFor(() => expect(container.textContent).toContain('v1勝率 60% → キャリブレーション済み 55%'))
  })
})
