/**
 * 試合一覧: 空状態の切替とデモ印の非表示
 *
 * muse T010 の観察:
 *  (1) 全行のレベル欄に内部表記 [__demo__] が併記され利用者に見える。
 *  (2) 絞り込み 0 件でも「試合が登録されていません」と出て誤解する。
 * 本テストは (a) 絞り込み 0 件と未登録の表示切替、(b) デモ印が内部表記で出ないことを確かめる。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, waitFor, fireEvent } from '@testing-library/react'
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

function makeMatch(id: number, extra: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id,
    tournament: `\u5927\u4f1a${id}`,
    tournament_level: 'IC',
    round: '\u6c7a\u52dd',
    date: `2026-01-${String(id).padStart(2, '0')}`,
    format: 'singles',
    player_a_id: 1,
    player_b_id: 2,
    annotation_status: 'complete',
    annotation_progress: 1,
    result: 'win',
    created_at: '', updated_at: '',
    player_a: { id: 1, name: '\u81ea\u5206' },
    player_b: { id: 2, name: `\u76f8\u624b${id}` },
    ...extra,
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

describe('MatchListPage 空状態の切替', () => {
  it('本当に未登録 (0 件) のときは従来の案内を出す', async () => {
    matchRows = []
    const { queryByTestId, container } = renderPage()
    await waitFor(() => expect(queryByTestId('match-empty-unregistered')).not.toBeNull())
    expect(queryByTestId('match-empty-filtered')).toBeNull()
    expect(container.textContent).toContain('\u8a66\u5408\u304c\u767b\u9332\u3055\u308c\u3066\u3044\u307e\u305b\u3093')
  })

  it('絞り込み 0 件のときは条件変更の案内と解除ボタンを出す', async () => {
    matchRows = [makeMatch(1)]
    const { getByTestId, queryByTestId, getByPlaceholderText, container } = renderPage()
    // まず表が出るまで待つ
    await waitFor(() => expect(container.textContent).toContain('\u5927\u4f1a1'))
    // マッチしない検索語を入れて 0 件にする
    const input = getByPlaceholderText('\u5927\u4f1a\u540d\u30fb\u9078\u624b\u540d\u30fb\u4f1a\u5834\u30fb\u5099\u8003\u3067\u691c\u7d22...') as HTMLInputElement
    fireEvent.change(input, { target: { value: 'ZZZ_NO_MATCH_ZZZ' } })
    await waitFor(() => expect(queryByTestId('match-empty-filtered')).not.toBeNull())
    // 未登録案内は出さない
    expect(queryByTestId('match-empty-unregistered')).toBeNull()
    expect(getByTestId('match-empty-filtered').textContent).toContain('\u6761\u4ef6\u306b\u5408\u3046\u8a66\u5408\u304c\u3042\u308a\u307e\u305b\u3093')
    expect(getByTestId('match-empty-filtered').textContent).toContain('\u7d5e\u308a\u8fbc\u307f\u3092\u89e3\u9664')
  })

  it('解除ボタンで検索がクリアされ表が戻る', async () => {
    matchRows = [makeMatch(1)]
    const { getByTestId, queryByTestId, getByPlaceholderText, container } = renderPage()
    await waitFor(() => expect(container.textContent).toContain('\u5927\u4f1a1'))
    const input = getByPlaceholderText('\u5927\u4f1a\u540d\u30fb\u9078\u624b\u540d\u30fb\u4f1a\u5834\u30fb\u5099\u8003\u3067\u691c\u7d22...') as HTMLInputElement
    fireEvent.change(input, { target: { value: 'ZZZ_NO_MATCH_ZZZ' } })
    await waitFor(() => expect(queryByTestId('match-empty-filtered')).not.toBeNull())
    fireEvent.click(getByTestId('match-empty-filtered').querySelector('button')!)
    await waitFor(() => expect(container.textContent).toContain('\u5927\u4f1a1'))
    expect(queryByTestId('match-empty-filtered')).toBeNull()
  })
})

describe('MatchListPage デモ印の非表示', () => {
  it('owner_team_display_id が __demo__ でも内部表記 [__demo__] を出さない', async () => {
    matchRows = [makeMatch(1, { owner_team_display_id: '__demo__', is_demo_public: true })]
    const { container } = renderPage()
    await waitFor(() => expect(container.textContent).toContain('\u5927\u4f1a1'))
    expect(container.textContent).not.toContain('__demo__')
    expect(container.textContent).not.toContain('[__demo__]')
  })

  it('通常の display_id は [ID] として表示する', async () => {
    matchRows = [makeMatch(1, { owner_team_display_id: 'TEAM7' })]
    const { container } = renderPage()
    await waitFor(() => expect(container.textContent).toContain('\u5927\u4f1a1'))
    expect(container.textContent).toContain('[TEAM7]')
  })
})
