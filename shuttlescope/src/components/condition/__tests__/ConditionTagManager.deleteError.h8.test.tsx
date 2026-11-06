/**
 * h8 item 606: deleting a condition tag must surface failure. When the DELETE
 * rejects, an inline alert appears for that row instead of silently vanishing.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

// Keep the real module (it has many exports evaluated at import time) and only
// stub the HTTP verbs we drive, otherwise unrelated exports become undefined
// and the component tree throws on render.
vi.mock('@/api/client', async () => {
  const actual = await vi.importActual<typeof import('@/api/client')>('@/api/client')
  return {
    ...actual,
    apiGet: vi.fn(),
    apiPost: vi.fn(),
    apiPut: vi.fn(),
    apiDelete: vi.fn(),
  }
})

// RoleGuard hides its children unless the signed-in user has an allowed role;
// in a unit test there is no auth context, so pass children through.
vi.mock('@/components/common/RoleGuard', () => ({
  RoleGuard: ({ children }: { children: ReactNode }) => <>{children}</>,
}))

import * as apiClient from '@/api/client'
import { ConditionTagManager } from '../ConditionTagManager'

const mockGet = vi.mocked(apiClient.apiGet)
const mockDelete = vi.mocked(apiClient.apiDelete)

function renderMgr() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ConditionTagManager playerId={1} isLight={false} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  mockGet.mockReset()
  mockDelete.mockReset()
  vi.spyOn(window, 'confirm').mockReturnValue(true)
})

describe('h8/606 condition tag delete failure is surfaced', () => {
  it('shows an inline alert when the delete request fails', async () => {
    mockGet.mockResolvedValue({
      success: true,
      data: [
        { id: 7, player_id: 1, label: 'Injury', start_date: '2026-01-01', end_date: null, color: '#3b82f6' },
      ],
    } as never)
    mockDelete.mockRejectedValue(new Error('delete failed'))

    renderMgr()
    // the row's delete button carries the label condition.tags.delete ('削除')
    const delBtn = await screen.findByRole('button', { name: '削除' })
    fireEvent.click(delBtn)
    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy())
  })
})
