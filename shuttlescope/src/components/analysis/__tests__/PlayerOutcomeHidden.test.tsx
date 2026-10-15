/**
 * player ロール: 勝敗に紐づくキーが API から消えても壊れず、勝敗を描かない
 *
 * バックエンドの player 応答サニタイザ (PLAYER_RESPONSE_RULES) は win_rate / wins / win_count /
 * effectiveness / winner / score_a / score_b / point_diff 等をレスポンスから落とす。
 * フロントは「キーが無い」ことを前提に、NaN% / 'undefined' / 勝敗文言を出さず、
 * 件数 (total_count / total_rallies / match_count) か、カードごと非表示に切り替える。
 * analyst / coach / admin の表示は従来どおり。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
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
  apiGet: vi.fn(),
  API_BASE_URL: '',
}))

vi.mock('@/components/court/CourtDiagram', () => ({
  CourtDiagram: ({ onZoneSelect }: { onZoneSelect?: (z: string) => void }) => (
    <button data-testid="zone-BL" onClick={() => onZoneSelect?.('BL')}>zone-BL</button>
  ),
}))

import * as apiClient from '@/api/client'
import i18n from '@/i18n'
import { DEFAULT_FILTERS } from '@/types'
import { EffectiveDistributionMap } from '../EffectiveDistributionMap'
import { SetComparison } from '../SetComparison'
import { TournamentComparison } from '../TournamentComparison'
import { SetIntervalSummary } from '../SetIntervalSummary'
import { ScoreProgression } from '../ScoreProgression'
import { RallyPickerModal } from '../RallyPickerModal'
import { IntervalReport } from '../IntervalReport'
import { CourtHeatModal } from '../CourtHeatModal'

const mockApi = vi.mocked(apiClient.apiGet)

class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}
;(globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = RO

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

const META = (n: number) => ({ sample_size: n, confidence: { level: 'low', stars: '★', label: 'low' } })

/** player に見せてはならない文字列 (NaN / undefined / 生の i18n キー / 勝敗文言) */
function expectNoLeak(text: string) {
  expect(text).not.toMatch(/NaN/)
  expect(text).not.toMatch(/undefined/)
  expect(text).not.toMatch(/match\.results\./)
  expect(text).not.toMatch(/勝ち|負け|勝率|得点率|失点/)
}

beforeEach(() => {
  mockApi.mockReset()
  mockRole = 'player'
})

describe('EffectiveDistributionMap / ZoneMapModal', () => {
  // サニタイズ後: win_count / win_rate / effectiveness が無い。total_count と top_zones は残る
  const playerResp = {
    success: true,
    data: { zone_effectiveness: { BR: { total_count: 5 }, BC: { total_count: 2 } }, top_zones: ['BR'] },
    meta: META(7),
  }
  const analystResp = {
    success: true,
    data: {
      zone_effectiveness: {
        BR: { total_count: 5, win_count: 3, win_rate: 0.6, effectiveness: 0.6 },
        BC: { total_count: 2, win_count: 1, win_rate: 0.5, effectiveness: 0.2 },
      },
      top_zones: ['BR'],
    },
    meta: META(7),
  }

  it('player: 勝率・有効度・得点数を描かず、件数を表示する (NaN% が出ない)', async () => {
    mockRoutes({ '/analysis/effective_distribution_map': playerResp })
    const { container } = wrap(<EffectiveDistributionMap playerId={1} filters={DEFAULT_FILTERS} />)
    await waitFor(() => expect(container.textContent).toContain('5件'))
    const text = container.textContent ?? ''
    expectNoLeak(text)
    expect(text).not.toContain('%')
    expect(text).not.toContain('有効度')
  })

  it('player: ゾーン詳細モーダルも 得点率 / 得点数 を描かない', async () => {
    mockRoutes({
      '/analysis/effective_distribution_map': playerResp,
      '/analysis/effective_distribution_map/zone_detail': {
        success: true,
        data: { zone: 'BR', total_count: 5, top_shot_types: [], hit_zones: [] },
        meta: { sample_size: 5 },
      },
    })
    const { container } = wrap(<EffectiveDistributionMap playerId={1} filters={DEFAULT_FILTERS} />)
    await waitFor(() => expect(container.textContent).toContain('5件'))
    fireEvent.click(screen.getAllByText('奥右')[0])
    await waitFor(() => expect(screen.getByText('総ストローク数')).toBeTruthy())
    const text = document.body.textContent ?? ''
    expect(text).not.toMatch(/NaN|undefined/)
    expect(text).not.toContain('得点率')
    expect(text).not.toContain('得点数')
  })

  it.each(['analyst', 'coach', 'admin'] as UserRole[])('%s: 従来どおり勝率・有効度を描く', async (r) => {
    mockRole = r
    mockRoutes({ '/analysis/effective_distribution_map': analystResp })
    const { container } = wrap(<EffectiveDistributionMap playerId={1} filters={DEFAULT_FILTERS} />)
    await waitFor(() => expect(container.textContent).toContain('60%'))
    expect(container.textContent).toContain('60.0%')
    expect(container.textContent).toContain('有効度')
  })
})

describe('SetComparison', () => {
  const playerResp = {
    data: [
      { set_number: 1, label: '第1セット', total_rallies: 20, avg_rally_length: 5.2 },
      { set_number: 2, label: '第2セット', total_rallies: 18, avg_rally_length: 4.8 },
    ],
    meta: META(38),
  }
  const analystResp = {
    data: playerResp.data.map((d, i) => ({ ...d, win_rate: i === 0 ? 0.6 : 0.4 })),
    meta: META(38),
  }

  it('player: 勝率を描かず、ラリー数を表示する', async () => {
    mockRoutes({ '/analysis/set_comparison': playerResp })
    const { container } = wrap(<SetComparison playerId={1} filters={DEFAULT_FILTERS} />)
    await waitFor(() => expect(container.textContent).toContain('20 ラリー'))
    const text = container.textContent ?? ''
    expectNoLeak(text)
    expect(text).not.toContain('%')
  })

  it.each(['analyst', 'coach', 'admin'] as UserRole[])('%s: 従来どおり勝率カードを描く', async (r) => {
    mockRole = r
    mockRoutes({ '/analysis/set_comparison': analystResp })
    const { container } = wrap(<SetComparison playerId={1} filters={DEFAULT_FILTERS} />)
    await waitFor(() => expect(container.textContent).toContain('60.0%'))
    expect(container.textContent).toContain('40.0%')
  })
})

describe('TournamentComparison', () => {
  const playerResp = {
    success: true,
    data: { levels: [{ level: 'IC', match_count: 3, avg_rally_length: 5.5, sample_size: 30 }] },
    meta: META(30),
  }
  const analystResp = {
    success: true,
    data: { levels: [{ level: 'IC', match_count: 3, win_rate: 0.5, avg_rally_length: 5.5, sample_size: 30 }] },
    meta: META(30),
  }

  it('player: 勝率列を描かず、試合数は残す', async () => {
    mockRoutes({ '/analysis/tournament_level_comparison': playerResp })
    const { container } = wrap(<TournamentComparison playerId={1} filters={DEFAULT_FILTERS} />)
    await waitFor(() => expect(container.querySelector('table')).not.toBeNull())
    const text = container.textContent ?? ''
    expectNoLeak(text)
    expect(text).not.toContain('%')
    expect(container.querySelectorAll('thead th')).toHaveLength(3)
    expect(container.querySelector('tbody tr')?.textContent).toContain('3')
  })

  it.each(['analyst', 'coach', 'admin'] as UserRole[])('%s: 従来どおり勝率列を描く', async (r) => {
    mockRole = r
    mockRoutes({ '/analysis/tournament_level_comparison': analystResp })
    const { container } = wrap(<TournamentComparison playerId={1} filters={DEFAULT_FILTERS} />)
    await waitFor(() => expect(container.textContent).toContain('50.0%'))
    expect(container.querySelectorAll('thead th')).toHaveLength(4)
  })
})

describe('SetIntervalSummary', () => {
  // サニタイズ後: score_a / score_b / winner / win_rate が無く、recent_loss_patterns / risky_shots は空
  const playerResp = {
    success: true,
    data: {
      set_num: 1, total_rallies: 30, avg_rally_length: 5.1, rally_length_trend: 'medium',
      recent_loss_patterns: [], effective_shots: [{ shot_type: 'clear', shot_type_ja: 'クリア', count: 4 }], risky_shots: [],
    },
    meta: META(30),
  }
  const coachResp = {
    success: true,
    data: {
      set_num: 1, score_a: 21, score_b: 15, winner: 'player_a', total_rallies: 36, avg_rally_length: 5.1,
      rally_length_trend: 'medium', recent_loss_patterns: [], effective_shots: [], risky_shots: [],
    },
    meta: META(36),
  }
  const lossTab = i18n.t('auto.SetIntervalSummary.k5')
  const shotsTab = i18n.t('auto.SetIntervalSummary.k6')

  function renderModal() {
    return wrap(
      <SetIntervalSummary
        setId={1} playerAName="自分" playerBName="相手" onClose={() => {}} onNextSet={() => {}} isMidGame={false}
      />,
    )
  }

  it('player: セットスコア・勝者を描かず、失点/ショットのタブも出さない', async () => {
    mockRoutes({ '/analysis/set_summary': playerResp })
    const { container } = renderModal()
    await waitFor(() => expect(container.textContent).toContain('30'))
    const text = container.textContent ?? ''
    expectNoLeak(text)
    expect(text).not.toContain('—') // 「自分 21 — 15 相手」の区切り (スコア行) が無い
    expect(screen.queryByText(lossTab)).toBeNull()
    expect(screen.queryByText(shotsTab)).toBeNull()
  })

  it.each(['analyst', 'coach', 'admin'] as UserRole[])('%s: 従来どおりスコアとタブを描く', async (r) => {
    mockRole = r
    mockRoutes({ '/analysis/set_summary': coachResp })
    const { container } = renderModal()
    await waitFor(() => expect(container.textContent).toContain('21'))
    expect(container.textContent).toContain('15')
    expect(screen.getByText(lossTab)).toBeTruthy()
    expect(screen.getByText(shotsTab)).toBeTruthy()
  })
})

describe('スコア推移系 (ScoreProgression / RallyPickerModal / IntervalReport)', () => {
  const sp = {
    success: true,
    data: { sets: [{ set_id: 1, set_num: 1, rallies: [{ rally_num: 1, score_a: 1, score_b: 0, winner: 'player_a', server: 'player_a', end_type: 'ace', rally_length: 3, point_diff: 1 }], momentum_changes: [] }] },
    meta: { sample_size: 10 },
  }
  const ir = {
    success: true,
    data: { match_id: 1, completed_set_num: 1, sets: [{ set_num: 1, rally_count: 10, wins: 6, win_rate_raw: 0.6, posterior_mean: 0.6, ci_low: 0.4, ci_high: 0.8 }], current_win_estimate: { mean: 0.6, ci_low: 0.4, ci_high: 0.8 }, prior: { alpha: 1, beta: 1 } },
    meta: META(10),
  }

  it('player: 3 コンポーネントとも何も描かず、スコア推移 / 推定勝率を取得しない', async () => {
    mockRoutes({ '/analysis/score_progression': sp, '/analysis/interval_report': ir })
    const a = wrap(<ScoreProgression matchId={1} />)
    const b = wrap(
      <RallyPickerModal matchId={1} matchLabel="m" initialSet={1} selectedRallyNum={null} onSelect={() => {}} onClear={() => {}} onClose={() => {}} />,
    )
    const c = wrap(<IntervalReport matchId={1} completedSet={3} />)
    await new Promise((r) => setTimeout(r, 30))
    expect(a.container.innerHTML).toBe('')
    expect(b.container.innerHTML).toBe('')
    expect(c.container.innerHTML).toBe('')
    expect(mockApi).not.toHaveBeenCalled()
  })

  it.each(['analyst', 'coach', 'admin'] as UserRole[])('%s: 従来どおり取得して描く', async (r) => {
    mockRole = r
    mockRoutes({ '/analysis/score_progression': sp, '/analysis/interval_report': ir })
    const a = wrap(<ScoreProgression matchId={1} />)
    const c = wrap(<IntervalReport matchId={1} completedSet={3} />)
    await waitFor(() => expect(c.container.textContent).toContain('60.0%'))
    expect(a.container.innerHTML).not.toBe('')
    expect(mockApi).toHaveBeenCalledWith('/analysis/score_progression', { match_id: 1 })
  })
})

describe('CourtHeatModal ゾーン詳細', () => {
  const heat = { success: true, data: { BL: 3 }, meta: META(5) }
  const detailPlayer = {
    success: true,
    data: { zone: 'BL', type: 'hit', count: 5, top_shot_types: [], transitions: [] },
    meta: { sample_size: 5 },
  }
  const detailAnalyst = {
    success: true,
    data: { zone: 'BL', type: 'hit', count: 5, wins: 3, win_rate: 0.6, top_shot_types: [], transitions: [] },
    meta: { sample_size: 5 },
  }
  const winRateLabel = i18n.t('court_heat_modal.stat_win_rate')

  function renderModal() {
    return wrap(
      <CourtHeatModal
        playerId={1} matches={[]} initialMatchId={null} initialLastN={null} initialTab="hit" onClose={() => {}}
      />,
    )
  }

  it('player: 勝率・得点数を描かない (件数は残す)', async () => {
    mockRoutes({ '/analysis/heatmap': heat, '/analysis/heatmap_zone_detail': detailPlayer })
    renderModal()
    fireEvent.click(await screen.findByTestId('zone-BL'))
    await waitFor(() => expect(screen.getByText(i18n.t('court_heat_modal.stat_strokes'))).toBeTruthy())
    const text = document.body.textContent ?? ''
    expect(text).not.toMatch(/NaN|undefined/)
    expect(text).not.toContain(winRateLabel)
    expect(text).not.toContain(i18n.t('court_heat_modal.stat_wins'))
  })

  it.each(['analyst', 'coach', 'admin'] as UserRole[])('%s: 従来どおり勝率・得点数を描く', async (r) => {
    mockRole = r
    mockRoutes({ '/analysis/heatmap': heat, '/analysis/heatmap_zone_detail': detailAnalyst })
    renderModal()
    fireEvent.click(await screen.findByTestId('zone-BL'))
    await waitFor(() => expect(screen.getByText(winRateLabel)).toBeTruthy())
    expect(document.body.textContent).toContain('60%')
  })
})
