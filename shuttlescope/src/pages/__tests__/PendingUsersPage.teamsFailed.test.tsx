import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

// \u30c1\u30fc\u30e0\u4e00\u89a7 (listTeams) \u306e\u53d6\u5f97\u5931\u6557\u3092\u300c\u5019\u88dc0\u4ef6\u300d\u3068\u533a\u5225\u3057\u3001\n// \u91cd\u8907\u30c1\u30fc\u30e0\u4f5c\u6210\u3092\u8a98\u767a\u3057\u306a\u3044 (item #609)\u3002
const apiGet = vi.fn()
const listTeams = vi.fn()
vi.mock('@/api/client', () => ({
  apiGet: (...a: unknown[]) => apiGet(...a),
  apiPost: vi.fn(),
  listTeams: (...a: unknown[]) => listTeams(...a),
  newIdempotencyKey: () => 'k',
}))

import PendingUsersPage from '../PendingUsersPage'

const pendingUser = {
  id: 1,
  username: 'u1',
  email: 'u1@example.com',
  email_verified: true,
  display_name: null,
  created_at: '2026-01-01',
  admin_notify_status: 'delivered',
  admin_notify_at: null,
  inquiry: null,
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <PendingUsersPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('PendingUsersPage team-list fetch failure', () => {
  beforeEach(() => {
    apiGet.mockReset()
    listTeams.mockReset()
    apiGet.mockResolvedValue({ success: true, data: [pendingUser] })
  })

  it('#609: shows a retryable error on the team field instead of a silent empty datalist', async () => {
    listTeams.mockRejectedValue(new Error('500'))
    renderPage()
    await waitFor(() => expect(screen.getByText('u1')).toBeTruthy())
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('\u30c1\u30fc\u30e0\u4e00\u89a7\u3092\u8aad\u307f\u8fbc\u3081\u307e\u305b\u3093\u3067\u3057\u305f')
    expect(screen.getByRole('button', { name: '\u518d\u8a66\u884c' })).toBeTruthy()
  })

  it('#609: no team-field error when the team list loads (even if empty)', async () => {
    listTeams.mockResolvedValue({ success: true, data: [] })
    renderPage()
    await waitFor(() => expect(screen.getByText('u1')).toBeTruthy())
    expect(screen.queryByText(/\u30c1\u30fc\u30e0\u4e00\u89a7\u3092\u8aad\u307f\u8fbc\u3081\u307e\u305b\u3093\u3067\u3057\u305f/)).toBeNull()
  })
})
