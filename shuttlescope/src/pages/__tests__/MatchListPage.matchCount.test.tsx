/**
 * 試合一覧: ヘッダーに表示中の件数を出す
 *
 * 2026-11-10 本番で、試合一覧に件数表示が無く、何件あるかが画面から
 * 分からないという観察があった。フィルタ後の件数 (matches.length) を
 * ヘッダーに `N 件` として出す。ローディング中・取得失敗時は出さない。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import type { UserRole } from '@/types'

let mockRole: UserRole | null = 'analyst'

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    role: mockRole,
    playerId: 1,
    teamName: null,
    hasRole: (allowed: UserRole[]) => (!mockRole ? false : mockRole === 'admin' ? true : allowed.includes(mockRole)),
    hasPageAccess: () => true,
  }),
}))

// 試合件数を変えられるように mock を外だしておく
let matchRows: Array<Record<string, unknown>> = []

vi.mock('@/api/client', () => ({
  apiGet: vi.fn(async (path: string) => {
    if (path === '/matches') {
      return { success: true, data: matchRows }
    }
    return { success: true, data: [] }
  }),
  apiPost: vi.fn(), apiPut: vi.fn(), apiDelete: vi.fn(),
  newIdempotencyKey: () => 'k',
  pipelineJobs: { list: vi.fn(async () => ({ success: true, data: [] })) },
  API_BASE_URL: '',
}))
vi.mock('@/components/analysis/PipelineJobBadge', () => ({ PipelineJobBadge: () => null }))
vi.mock('@/components/annotation/QuickStartModal', () => ({ QuickStartModal: () => null }))
vi.mock('@/components/video/DownloadOptionsModal', () => ({ DownloadOptionsModal: () => null }))

import { MatchListPage } from '../MatchListPage'

function makeMatch(id: number): Record<string, unknown> {
  return {
    id,
    tournament: `大会${id}`,
    tournament_level: 'IC',
    round: '決勝',
    date: `2026-01-${String(id).padStart(2, '0')}`,
    format: 'singles',
    player_a_id: 1,
    player_b_id: 2,
    annotation_status: 'complete',
    annotation_progress: 1,
    result: 'win',
    created_at: '', updated_at: '',
    player_a: { id: 1, name: '自分' },
    player_b: { id: 2, name: `相手${id}` },
  }
}

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

beforeEach(() => {
  mockRole = 'analyst'
  matchRows = []
})

describe('MatchListPage 件数表示', () => {
  it('複数件: ヘッダーに N 件 を出す', async () => {
    matchRows = [makeMatch(1), makeMatch(2), makeMatch(3)]
    const { getByTestId } = renderPage()
    await waitFor(() => expect(getByTestId('match-count').textContent).toContain('3'))
    expect(getByTestId('match-count').textContent).toBe('3 件')
  })

  it('0 件: 空表示でも件数バッジ自体はつかない (空ステートが出る)', async () => {
    matchRows = []
    const { container, queryByTestId } = renderPage()
    // ローディング完了後、空ステート (ガイドへの導導) が出るまで待つ
    await waitFor(() => expect(container.textContent).toBeTruthy())
    // 0 件でも件数表示自体は出る (ローディング完了しエラー無しのため)
    await waitFor(() => expect(queryByTestId('match-count')).not.toBeNull())
    expect(queryByTestId('match-count')!.textContent).toBe('0 件')
  })
})
