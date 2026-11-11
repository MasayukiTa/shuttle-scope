/**
 * 試合登録フォーム: 大会レベル / ラウンドは必須。未選択のまま送信したら、
 * 汎用 alert ではなく該当欄の直下に日本語のインライン案内を出し、送信 (apiPost) を
 * 行わない。症状: 必須印 (*) はあるが未選択時の個別案内が無く、利用者が原因に
 * 気づけなかった。red->green 固定。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import type { UserRole } from '@/types'
import { apiPost } from '@/api/client'

let mockRole: UserRole | null = 'coach'

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    role: mockRole,
    playerId: null,
    teamName: 'T',
    hasRole: (allowed: UserRole[]) => (!mockRole ? false : mockRole === 'admin' ? true : allowed.includes(mockRole)),
    hasPageAccess: () => true,
  }),
}))

vi.mock('@/api/client', () => ({
  apiGet: vi.fn(async () => ({ success: true, data: [] })),
  apiPost: vi.fn(async () => ({ success: true, data: { match: { id: 1 } } })),
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

function openForm(container: HTMLElement) {
  const openBtn = Array.from(container.querySelectorAll('button')).find(
    (b) => (b.textContent ?? '').includes('試合登録'),
  )
  if (!openBtn) throw new Error('open button not found')
  fireEvent.click(openBtn)
}

beforeEach(() => {
  mockRole = 'coach'
  vi.clearAllMocks()
})

describe('MatchListPage required level/round inline guidance', () => {
  it('未選択で送信するとインライン案内が出て apiPost は呼ばれない', async () => {
    const { container } = renderPage()
    await waitFor(() => expect(container.querySelector('button')).toBeTruthy())
    openForm(container)

    const form = await waitFor(() => {
      const f = container.querySelector('form')
      if (!f) throw new Error('form not shown')
      return f as HTMLFormElement
    })

    // 未選択時は案内がまだ出ていない
    expect(container.textContent).not.toContain('大会レベルを選択してください')
    expect(container.textContent).not.toContain('ラウンドを選択してください')

    fireEvent.submit(form)

    await waitFor(() => {
      expect(container.textContent).toContain('大会レベルを選択してください')
    })
    expect(container.textContent).toContain('ラウンドを選択してください')
    expect(apiPost).not.toHaveBeenCalled()
  })
})
