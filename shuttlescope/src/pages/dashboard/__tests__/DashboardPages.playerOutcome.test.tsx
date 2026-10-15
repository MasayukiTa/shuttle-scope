/**
 * ダッシュボード各ページ: player には勝敗 (W/L 接尾辞・スコア推移・推定勝率) を出さない
 *
 * - 振り返り: 試合セレクタの接尾辞が `m.result === 'win' ? 'W' : 'L'` だと、
 *   API が result を返さない player では全試合が「L」になる。
 * - 概要: スコア推移 / インターバルレポートのカードを出さない。
 *   サーブ勝率カードは server_win_rate が無いとき読み込み中のまま固まらない。
 * - 速報: 試合セレクタの W/L・地点 (ラリー) ピッカー・インターバルレポートを出さない。
 * analyst / coach / admin の表示は従来どおり。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { UserRole } from '@/types'

let mockRole: UserRole | null = 'player'
let mockDescriptive: Record<string, unknown> = {}

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    role: mockRole,
    hasRole: (allowed: UserRole[]) => (!mockRole ? false : mockRole === 'admin' ? true : allowed.includes(mockRole)),
  }),
}))

vi.mock('@/api/client', () => ({
  apiGet: vi.fn(async (path: string) => {
    if (path.includes('descriptive')) return { success: true, data: mockDescriptive }
    return { success: true, data: {} }
  }),
  API_BASE_URL: '',
}))

// 子コンポーネントは目印だけ出す。SearchableSelect は選択肢の「ラベル + 接尾辞」を全部描く。
vi.mock('@/components/common/SearchableSelect', () => ({
  SearchableSelect: ({ options }: { options: { label: string; suffix?: string }[] }) => (
    <div>{options.map((o, i) => <span key={i} data-testid="opt">{`${o.label}|${o.suffix ?? ''}`}</span>)}</div>
  ),
}))
vi.mock('@/components/analysis/ScoreProgression', () => ({ ScoreProgression: () => <div>MOCK_SCORE_PROGRESSION</div> }))
vi.mock('@/components/analysis/IntervalReport', () => ({ IntervalReport: () => <div>MOCK_INTERVAL_REPORT</div> }))
vi.mock('@/components/analysis/SetIntervalSummary', () => ({ SetIntervalSummary: () => null }))
vi.mock('@/components/analysis/RallyPickerModal', () => ({ RallyPickerModal: () => <div>MOCK_RALLY_PICKER</div> }))
vi.mock('@/components/analysis/ConfidenceCalibration', () => ({ ConfidenceCalibration: () => null }))
vi.mock('@/components/analysis/CourtHeatModal', () => ({ CourtHeatModal: () => null }))
vi.mock('@/components/court/CourtDiagram', () => ({ CourtDiagram: () => null }))
vi.mock('@/components/analysis/PreLossPatterns', () => ({ PreLossPatterns: () => null }))
vi.mock('@/components/analysis/PreWinPatterns', () => ({ PreWinPatterns: () => null }))
vi.mock('@/components/analysis/EffectiveDistributionMap', () => ({ EffectiveDistributionMap: () => null }))
vi.mock('@/components/analysis/ReceivedVulnerabilityMap', () => ({ ReceivedVulnerabilityMap: () => null }))
vi.mock('@/components/analysis/SetComparison', () => ({ SetComparison: () => null }))
vi.mock('@/components/analysis/RallySequencePatterns', () => ({ RallySequencePatterns: () => null }))
vi.mock('@/components/analysis/RallyClipNavigator', () => ({ RallyClipNavigator: () => null }))
vi.mock('@/components/analysis/FlashAdvicePanel', () => ({ FlashAdvicePanel: () => null }))
vi.mock('@/components/analysis/RecommendationRanking', () => ({ RecommendationRanking: () => null }))
vi.mock('@/components/analysis/QuickSummaryCard', () => ({ QuickSummaryCard: () => null }))
vi.mock('@/components/dashboard/live/AnomalyBanner', () => ({ AnomalyBanner: () => null }))
vi.mock('@/components/dashboard/live/IntervalSuggestionsStrip', () => ({ IntervalSuggestionsStrip: () => null }))
vi.mock('@/components/dashboard/live/BenchModeToggle', () => ({
  BenchModeToggle: () => null,
  useBenchMode: () => [false, () => {}],
}))
vi.mock('@/hooks/useReviewBundle', () => ({ useReviewBundle: () => ({ data: undefined, isLoading: false }) }))
vi.mock('recharts', () => ({
  BarChart: () => null, Bar: () => null, XAxis: () => null, YAxis: () => null, Tooltip: () => null,
  ResponsiveContainer: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
}))

import { DashboardReviewPage } from '../DashboardReviewPage'
import { DashboardLivePage } from '../DashboardLivePage'
import { DashboardOverviewPage } from '../DashboardOverviewPage'
import i18n from '@/i18n'

// サニタイズ後の player 向け試合サマリ: result / set_scores の中身が無い
const playerMatches = [
  { match_id: 1, opponent: '相手A', tournament: '大会X', tournament_level: 'IC', date: '2026-01-01', rally_count: 30, format: 'singles', set_count: 2, set_scores: [] },
  { match_id: 2, opponent: '相手B', tournament: '大会Y', tournament_level: 'IS', date: '2026-02-01', rally_count: 40, format: 'singles', set_count: 2, set_scores: [] },
]
const coachMatches = [
  { ...playerMatches[0], result: 'win', set_scores: [{ set_num: 1, score_player: 21, score_opponent: 10, won: true }] },
  { ...playerMatches[1], result: 'loss', set_scores: [{ set_num: 1, score_player: 12, score_opponent: 21, won: false }] },
]
const filters = { result: 'all', tournamentLevel: null, dateFrom: null, dateTo: null } as never

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}
const opts = (c: HTMLElement) => Array.from(c.querySelectorAll('[data-testid="opt"]')).map((e) => e.textContent ?? '')

beforeEach(() => {
  mockRole = 'player'
  mockDescriptive = {}
})

describe('DashboardReviewPage', () => {
  const step3 = i18n.t('auto.DashboardReviewPage.step3_score')

  it('player: 試合セレクタに W/L を付けず、スコア推移セクションを出さない', () => {
    const { container } = wrap(<DashboardReviewPage playerId={1} filters={filters} matches={playerMatches as never} />)
    // 試合セレクタはスコア推移セクションの中にあるので、player には出ない (出ても接尾辞は付かない)
    expect(opts(container).every((s) => s.endsWith('|'))).toBe(true)
    expect(container.textContent).not.toContain('MOCK_SCORE_PROGRESSION')
    expect(container.textContent).not.toContain(step3)
    expect(container.textContent).not.toMatch(/NaN|undefined/)
  })

  it.each(['analyst', 'coach', 'admin'] as UserRole[])('%s: 従来どおり 勝/負 とスコア推移を出す', (r) => {
    mockRole = r
    const { container } = wrap(<DashboardReviewPage playerId={1} filters={filters} matches={coachMatches as never} />)
    expect(opts(container)).toEqual(['2026-01-01 vs 相手A|勝', '2026-02-01 vs 相手B|負'])
    expect(container.textContent).toContain(step3)
  })
})

describe('DashboardLivePage', () => {
  const pickLabel = i18n.t('analysis.flash.rally_select')
  const reportTitle = i18n.t('analysis.interval_report.title')

  it('player: 試合セレクタに W/L・スコアを付けず、地点ピッカーとインターバルレポートを出さない', () => {
    const { container } = wrap(<DashboardLivePage playerId={1} filters={filters} matches={playerMatches as never} />)
    // 速報セレクタの 2 件のみ (インターバルレポート側の試合セレクタは出ない)。接尾辞は空
    expect(opts(container)).toEqual(['2026-01-01 vs 相手A|', '2026-02-01 vs 相手B|'])
    const text = container.textContent ?? ''
    expect(text).not.toMatch(/NaN|undefined/)
    expect(text).not.toContain(pickLabel)
    expect(text).not.toContain(reportTitle)
    expect(text).not.toContain('MOCK_INTERVAL_REPORT')
    expect(text).not.toContain('MOCK_RALLY_PICKER')
  })

  it.each(['analyst', 'coach', 'admin'] as UserRole[])('%s: 従来どおり W/L・地点ピッカー・インターバルレポートを出す', (r) => {
    mockRole = r
    const { container } = wrap(<DashboardLivePage playerId={1} filters={filters} matches={coachMatches as never} />)
    const o = opts(container)
    expect(o.some((s) => s.endsWith('|21-10○'))).toBe(true)
    expect(o.some((s) => s.endsWith('|L') || s.endsWith('|12-21●'))).toBe(true)
    expect(container.textContent).toContain(pickLabel)
    expect(container.textContent).toContain(reportTitle)
  })
})

describe('DashboardOverviewPage', () => {
  it('player: スコア推移とインターバルレポートのカードを出さない', () => {
    const { container } = wrap(
      <DashboardOverviewPage playerId={1} filters={filters} filterApiParams={{}} matches={playerMatches as never} loadingMatches={false} />,
    )
    const text = container.textContent ?? ''
    // 試合未選択でもカード見出しは出る (analyst 側のテスト参照) ので、見出しで判定する
    expect(text).not.toContain(i18n.t('analysis.score_progression.title'))
    expect(text).not.toContain(i18n.t('analysis.interval_report.title'))
    expect(text).not.toContain('MOCK_SCORE_PROGRESSION')
    expect(text).not.toContain('MOCK_INTERVAL_REPORT')
    expect(text).not.toMatch(/NaN|undefined/)
  })

  it.each(['analyst', 'coach', 'admin'] as UserRole[])('%s: 従来どおりスコア推移とインターバルレポートを出す', (r) => {
    mockRole = r
    const { container } = wrap(
      <DashboardOverviewPage playerId={1} filters={filters} filterApiParams={{}} matches={coachMatches as never} loadingMatches={false} />,
    )
    // 試合未選択のときは「試合を選択してください」の案内だが、カード見出しは出る
    expect(container.textContent).toContain(i18n.t('analysis.score_progression.title'))
    expect(container.textContent).toContain(i18n.t('analysis.interval_report.title'))
  })

  it('coach: server_win_rate が無いサーブ勝率カードは読み込み中のまま固まらず「データなし」を出す', async () => {
    mockRole = 'coach'
    mockDescriptive = { total_matches: 1, total_rallies: 10, avg_rally_length: 5, end_type_distribution: {}, rally_length_histogram: [] }
    const { container } = wrap(
      <DashboardOverviewPage playerId={1} filters={filters} filterApiParams={{}} matches={coachMatches as never} loadingMatches={false} />,
    )
    const serveTitle = i18n.t('auto.DashboardOverviewPage.k9')
    await waitFor(() => {
      const card = Array.from(container.querySelectorAll('h2')).find((h) => h.textContent === serveTitle)?.closest('div.rounded-ss-lg')
      expect(card?.textContent).toContain(i18n.t('auto.DashboardOverviewPage.k3'))
    })
  })
})
