/**
 * 試合一覧 (MatchListPage / MatchRow / MatchCard): player には勝敗・スコアを出さない
 *
 * 製品ルール: player に勝敗結果を見せない。API は player 応答から result / final_score を落とすため、
 * そのまま描くと t('match.results.undefined') の生キーが出る。列・カード行・結果ソートごと隠す。
 * analyst / coach / admin の表示は従来どおり。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import type { UserRole } from '@/types'

let mockRole: UserRole | null = 'player'

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    role: mockRole,
    playerId: 1,
    teamName: null,
    hasRole: (allowed: UserRole[]) => (!mockRole ? false : mockRole === 'admin' ? true : allowed.includes(mockRole)),
  }),
}))

const baseMatch = {
  id: 7, tournament: '大会X', tournament_level: 'IC', round: '決勝', date: '2026-01-01', format: 'singles',
  player_a_id: 1, player_b_id: 2, annotation_status: 'complete', annotation_progress: 1,
  created_at: '', updated_at: '', player_b: { id: 2, name: '相手A' },
}
const playerMatch = { ...baseMatch } // サニタイズ後: result / final_score が無い
const coachMatch = { ...baseMatch, result: 'win', final_score: '21-15, 21-10' }

vi.mock('@/api/client', () => ({
  apiGet: vi.fn(async (path: string) => {
    if (path === '/matches') {
      return { success: true, data: [mockRole === 'player' ? playerMatch : coachMatch] }
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
import { MatchRow } from '@/components/matchList/MatchRow'
import { MatchCard } from '@/components/matchList/MatchCard'
import type { Match } from '@/types'

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

const noop = () => {}

beforeEach(() => {
  mockRole = 'player'
})

describe('MatchRow / MatchCard', () => {
  function renderRow(m: unknown) {
    return render(
      <MemoryRouter>
        <table><tbody>
          <MatchRow match={m as Match} selected={false} onToggleSelect={noop} onDownload={noop} onEdit={noop}
            deleteConfirmId={null} onDeleteConfirm={noop} onDeleteExecute={noop} />
        </tbody></table>
      </MemoryRouter>,
    )
  }
  function renderCard(m: unknown) {
    return render(
      <MemoryRouter>
        <MatchCard match={m as Match} onDownload={noop} onEdit={noop}
          deleteConfirmId={null} onDeleteConfirm={noop} onDeleteExecute={noop} />
      </MemoryRouter>,
    )
  }

  it('player: 行に結果セル・スコアを描かず、生キーも出ない', () => {
    const { container } = renderRow(playerMatch)
    const text = container.textContent ?? ''
    expect(text).not.toMatch(/match\.results|undefined|NaN/)
    expect(text).not.toMatch(/勝ち|負け|不明/)
    // チェックボックス / 日付 / 大会 / レベル / 形式 / 対戦相手 / 進捗 / 操作 = 8 セル (結果セル無し)
    expect(container.querySelectorAll('td')).toHaveLength(8)
  })

  it('player: カードに結果ラベル・スコアを描かず、生キーも出ない', () => {
    const { container } = renderCard(playerMatch)
    const text = container.textContent ?? ''
    expect(text).not.toMatch(/match\.results|undefined|NaN/)
    expect(text).not.toMatch(/勝ち|負け|不明/)
    expect(text).not.toContain('21-15')
  })

  it.each(['analyst', 'coach', 'admin'] as UserRole[])('%s: 従来どおり結果とスコアを描く', (r) => {
    mockRole = r
    const row = renderRow(coachMatch)
    expect(row.container.textContent).toContain('勝ち')
    expect(row.container.textContent).toContain('21-15, 21-10')
    expect(row.container.querySelectorAll('td')).toHaveLength(9)
    const card = renderCard(coachMatch)
    expect(card.container.textContent).toContain('勝ち')
    expect(card.container.textContent).toContain('21-15, 21-10')
  })
})

describe('MatchListPage', () => {
  it('player: 結果列 (ヘッダ・ソート) と結果・スコアを描かない', async () => {
    const { container } = renderPage()
    await waitFor(() => expect(container.textContent).toContain('大会X'))
    const text = container.textContent ?? ''
    expect(text).not.toMatch(/match\.results|undefined|NaN/)
    expect(text).not.toMatch(/勝ち|負け/)
    // ヘッダ: 選択 / 日付 / 大会 / レベル / 形式 / 対戦相手 / 進捗 / 操作 = 8 列 (結果列無し)
    expect(container.querySelectorAll('thead th')).toHaveLength(8)
  })

  it.each(['analyst', 'coach', 'admin'] as UserRole[])('%s: 従来どおり結果列・結果ソート・スコアを描く', async (r) => {
    mockRole = r
    const { container } = renderPage()
    await waitFor(() => expect(container.textContent).toContain('大会X'))
    expect(container.querySelectorAll('thead th')).toHaveLength(9)
    expect(container.textContent).toContain('勝ち')
    expect(container.textContent).toContain('21-15, 21-10')
  })
})
