/**
 * 試合一覧: リアルタイム解析 (QuickStart) ボタンの表示はバックエンドの権限に合わせる
 *
 * POST /matches/quick-start は player を 403 で拒否する (routers/matches.py quick_start_match)。
 * 最後まで入力させて失敗させないよう、player にはボタンを出さない。
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
    hasPageAccess: () => true,
  }),
}))

vi.mock('@/api/client', () => ({
  apiGet: vi.fn(async (path: string) => {
    if (path === '/matches') {
      return {
        success: true,
        data: [{
          id: 7, tournament: '大会X', tournament_level: 'IC', round: '決勝', date: '2026-01-01', format: 'singles',
          player_a_id: 1, player_b_id: 2, annotation_status: 'complete', annotation_progress: 1,
          created_at: '', updated_at: '', player_b: { id: 2, name: '相手A' },
        }],
      }
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

function hasQuickStartButton(container: HTMLElement): boolean {
  return Array.from(container.querySelectorAll('button')).some(
    (b) => (b.textContent ?? '').trim() === 'リアルタイム解析',
  )
}

beforeEach(() => {
  mockRole = 'player'
})

describe('MatchListPage QuickStart button', () => {
  it('player: 出さない', async () => {
    const { container } = renderPage()
    await waitFor(() => expect(container.textContent).toContain('大会X'))
    expect(hasQuickStartButton(container)).toBe(false)
  })

  it.each(['analyst', 'coach', 'admin'] as UserRole[])('%s: 出す', async (r) => {
    mockRole = r
    const { container } = renderPage()
    await waitFor(() => expect(container.textContent).toContain('大会X'))
    expect(hasQuickStartButton(container)).toBe(true)
  })
})
