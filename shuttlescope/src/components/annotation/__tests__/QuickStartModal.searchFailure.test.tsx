/**
 * QuickStart: 対戦相手検索の失敗を「候補 0 件」と扱わない。
 * 失敗中に暫定登録できると、既存の対戦相手がいても同一人物の暫定選手を重複作成してしまう。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

let searchShouldFail = true

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ role: 'analyst', playerId: 1, teamName: null }),
}))

vi.mock('@/api/client', () => ({
  apiGet: vi.fn(async (path: string) => {
    if (path === '/players/search') {
      if (searchShouldFail) throw new Error('network')
      return { success: true, data: [] }
    }
    return { success: true, data: [] }
  }),
  apiPost: vi.fn(),
}))

import { QuickStartModal } from '../QuickStartModal'

function renderModal() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <QuickStartModal onClose={vi.fn()} onStarted={vi.fn()} />
    </QueryClientProvider>,
  )
}

describe('QuickStartModal opponent search failure', () => {
  beforeEach(() => {
    searchShouldFail = true
  })

  it('shows an error with retry and hides the provisional-registration button', async () => {
    renderModal()
    fireEvent.change(screen.getByPlaceholderText('相手選手名を入力'), { target: { value: '山田' } })

    expect(await screen.findByRole('alert')).toHaveTextContent('検索できません')
    expect(screen.getByRole('button', { name: '再試行' })).toBeInTheDocument()
    expect(screen.queryByText(/暫定登録して開始/)).not.toBeInTheDocument()
  })

  it('offers provisional registration again once the retry succeeds with 0 candidates', async () => {
    renderModal()
    fireEvent.change(screen.getByPlaceholderText('相手選手名を入力'), { target: { value: '山田' } })
    const retry = await screen.findByRole('button', { name: '再試行' })
    searchShouldFail = false
    fireEvent.click(retry)

    await waitFor(() => {
      expect(screen.getByText(/暫定登録して開始/)).toBeInTheDocument()
    })
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
