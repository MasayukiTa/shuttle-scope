/**
 * QuickStart: 暫定登録（provisional）の導線を権限と一致させる。
 * POST /players は analyst / admin のみ許可されるため、coach には暫定登録 CTA を出さず
 * 権限不足を明示する（保存前に 403 へ進ませない）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

let currentRole = 'coach'

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ role: currentRole, playerId: 1, teamName: null }),
}))

vi.mock('@/api/client', () => ({
  apiGet: vi.fn(async () => ({ success: true, data: [] })),
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

describe('QuickStartModal provisional-registration role gating', () => {
  beforeEach(() => {
    currentRole = 'coach'
  })

  it('hides the provisional-registration CTA and explains the missing permission for coach', async () => {
    renderModal()
    fireEvent.change(screen.getByPlaceholderText('相手選手名を入力'), { target: { value: '山田' } })
    expect(await screen.findByText(/Analyst/)).toBeInTheDocument()
    expect(screen.queryByText(/暫定登録して開始/)).not.toBeInTheDocument()
  })

  it('shows the provisional-registration CTA for analyst', async () => {
    currentRole = 'analyst'
    renderModal()
    fireEvent.change(screen.getByPlaceholderText('相手選手名を入力'), { target: { value: '山田' } })
    expect(await screen.findByText(/暫定登録して開始/)).toBeInTheDocument()
  })
})
