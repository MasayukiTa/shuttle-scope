/**
 * 試合一覧の空状態の切り替え (w52 / muse T010)
 *
 * - 本当に未登録 (フィルタ無しで 0 件) のときだけ、従来の「試合が登録されていません」案内を出す。
 * - 絞り込み中に 0 件になったら「条件に合う試合がありません。条件を変えてください。」と
 *   絞り込み解除ボタンを出す (未登録と誤解させない)。
 * - デモ試合でも内部表記 [__demo__] は画面に出さず、「デモ」バッジに置き換える。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, cleanup, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import '@/i18n'
import i18n from '@/i18n'

let mockRole = 'coach'
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    role: mockRole,
    playerId: 1,
    teamName: null,
    user: { id: 1, username: 'coach', role: mockRole },
    hasRole: () => true,
    hasPageAccess: () => true,
  }),
}))

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

interface MatchRecord { id: number; [k: string]: unknown }
// allMatches はサーバ側フィルタ (tournament_level) に応じて変わる。
// level 指定ありなら 0 件 (絞り込み 0 件)、指定なしなら baseMatches を返す。
let baseMatches: MatchRecord[] = []
const apiGetMock = vi.fn((path: string, params?: Record<string, unknown>) => {
  if (path === '/matches') {
    if (params && params.tournament_level) return Promise.resolve({ success: true, data: [] })
    return Promise.resolve({ success: true, data: baseMatches })
  }
  return Promise.resolve({ success: true, data: [] })
})
vi.mock('@/api/client', () => ({
  apiGet: (...a: unknown[]) => apiGetMock(...(a as [string, Record<string, unknown>?])),
  apiPost: vi.fn(() => Promise.resolve({ success: true, data: {} })),
  apiPut: vi.fn(() => Promise.resolve({ success: true, data: {} })),
  apiDelete: vi.fn(() => Promise.resolve({ success: true, data: {} })),
  apiGetBlob: vi.fn(() => Promise.resolve({ blob: new Blob(), filename: 'x' })),
  newIdempotencyKey: () => 'test-key',
  pipelineJobs: { list: vi.fn(async () => ({ success: true, data: [] })) },
  API_BASE_URL: '',
}))
vi.mock('@/components/analysis/PipelineJobBadge', () => ({ PipelineJobBadge: () => null }))
vi.mock('@/components/annotation/QuickStartModal', () => ({ QuickStartModal: () => null }))
vi.mock('@/components/video/DownloadOptionsModal', () => ({ DownloadOptionsModal: () => null }))

import { MatchListPage } from '@/pages/MatchListPage'

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <MatchListPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function makeMatch(over: Partial<MatchRecord> = {}): MatchRecord {
  return {
    id: 1,
    date: '2026-01-01',
    tournament: 'Tournament A',
    tournament_level: 'IC',
    round: 'F',
    format: 'singles',
    result: 'win',
    annotation_status: 'pending',
    annotation_progress: 0,
    player_a_id: 10,
    player_b_id: 20,
    player_a: { id: 10, name: 'Alice', team: 'T1' },
    player_b: { id: 20, name: 'Bob', team: 'T2' },
    ...over,
  }
}

beforeEach(() => {
  baseMatches = []
  apiGetMock.mockClear()
  mockNavigate.mockClear()
  mockRole = 'coach'
  i18n.changeLanguage('ja')
})
afterEach(() => cleanup())

describe('MatchListPage empty states (w52 T010)', () => {
  it('本当に未登録のときは従来の案内を出す', async () => {
    baseMatches = []
    renderPage()
    await waitFor(() => expect(screen.getByTestId('match-empty-unregistered')).toBeTruthy())
    expect(screen.queryByTestId('match-empty-filtered')).toBeNull()
    expect(screen.getByText(i18n.t('auto.MatchListPage.k37') as string)).toBeTruthy()
  })

  it('大会レベルで絞り込んで 0 件なら、条件変更の案内と解除ボタンを出す (未登録案内は出さない)', async () => {
    baseMatches = [makeMatch()]
    const { container } = renderPage()
    await waitFor(() => expect(container.textContent).toContain('Tournament A'))

    // tournament_level の select に IC を入れる (全 select へ発火させて該当を拾う)
    const selects = screen.getAllByRole('combobox') as HTMLSelectElement[]
    for (const s of selects) {
      if (Array.from(s.options).some((o) => o.value === 'IC')) {
        fireEvent.change(s, { target: { value: 'IC' } })
      }
    }

    await waitFor(() => expect(screen.getByTestId('match-empty-filtered')).toBeTruthy())
    expect(screen.queryByTestId('match-empty-unregistered')).toBeNull()
    expect(screen.getByText(i18n.t('match.list.empty_filtered') as string)).toBeTruthy()
    expect(screen.getByText(i18n.t('match.list.clear_filters') as string)).toBeTruthy()
  })

  it('テキスト検索で 0 件のとき、解除ボタンで全件に戻る', async () => {
    baseMatches = [makeMatch()]
    const { container } = renderPage()
    await waitFor(() => expect(container.textContent).toContain('Tournament A'))

    const textInputs = Array.from(container.querySelectorAll('input')).filter(
      (e) => (e as HTMLInputElement).type === 'text',
    ) as HTMLInputElement[]
    expect(textInputs.length).toBeGreaterThan(0)
    fireEvent.change(textInputs[0], { target: { value: 'ZZZ-no-such-match' } })

    await waitFor(() => expect(screen.getByTestId('match-empty-filtered')).toBeTruthy())

    fireEvent.click(screen.getByText(i18n.t('match.list.clear_filters') as string))
    await waitFor(() => expect(container.textContent).toContain('Tournament A'))
    expect(screen.queryByTestId('match-empty-filtered')).toBeNull()
  })

  it('デモ試合でも内部表記 [__demo__] は出さず、デモ バッジを出す', async () => {
    baseMatches = [makeMatch({ owner_team_display_id: '__demo__', owner_team_display_name: 'DEMO' })]
    const { container } = renderPage()
    await waitFor(() => expect(container.textContent).toContain('Tournament A'))

    expect(container.textContent).not.toContain('__demo__')
    expect(screen.getAllByText(i18n.t('match.list.demo_public_badge') as string).length).toBeGreaterThan(0)
  })

  it('通常チームの試合は登録チーム ID を括弧付きで出す', async () => {
    baseMatches = [makeMatch({ owner_team_display_id: 'TEAM7', owner_team_display_name: 'Team Seven' })]
    const { container } = renderPage()
    await waitFor(() => expect(container.textContent).toContain('Tournament A'))
    expect(container.textContent).toContain('[TEAM7]')
  })
})
