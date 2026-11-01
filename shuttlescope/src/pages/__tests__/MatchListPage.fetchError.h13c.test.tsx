/**
 * #647: MatchList 本体の取得失敗を「試合 0 件」の初回利用状態へ倒さない。
 *
 * GET /matches が失敗したときは、「まだ試合が無い」用の「はじめに」誘導ではなく、
 * 明示的なエラー状態と再試行を出す。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import type { UserRole } from '@/types'

let failMatches = true

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    role: 'analyst' as UserRole,
    playerId: 1,
    teamName: null,
    hasRole: () => true,
    hasPageAccess: () => true,
  }),
}))

vi.mock('@/api/client', () => ({
  apiGet: vi.fn(async (path: string) => {
    if (path === '/matches') {
      if (failMatches) throw new Error('network down')
      return { success: true, data: [] }
    }
    return { success: true, data: [] }
  }),
  apiPost: vi.fn(),
  apiPut: vi.fn(),
  apiDelete: vi.fn(),
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

beforeEach(() => {
  failMatches = true
})

describe('MatchListPage /matches 取得失敗時のエラー状態', () => {
  it('取得失敗ではエラー表示と再試行を出し、「はじめに」空状態に倒さない', async () => {
    const { container, queryByRole } = renderPage()
    await waitFor(() => expect(queryByRole('alert')).toBeTruthy())
    const retry = Array.from(container.querySelectorAll('button')).some(
      (b) => (b.textContent ?? '').includes('再試行'),
    )
    expect(retry).toBe(true)
    // 正常 0 件の「はじめに」 CTA は出さない
    const toGettingStarted = Array.from(container.querySelectorAll('button')).some(
      (b) => (b.textContent ?? '').includes('はじめに'),
    )
    expect(toGettingStarted).toBe(false)
  })

  it('成功した 0 件は従来通り「はじめに」空状態を出す', async () => {
    failMatches = false
    const { container, queryByRole } = renderPage()
    await waitFor(() =>
      expect(
        Array.from(container.querySelectorAll('button')).some((b) =>
          (b.textContent ?? '').includes('はじめに'),
        ),
      ).toBe(true),
    )
    expect(queryByRole('alert')).toBeNull()
  })
})
