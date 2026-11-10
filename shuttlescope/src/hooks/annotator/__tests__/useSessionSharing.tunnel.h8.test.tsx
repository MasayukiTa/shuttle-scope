/**
 * h8 item 618: tunnel status fetch failure must not be read as "stopped".
 * While the status is unconfirmed (loading or error), tunnelUnconfirmed is true
 * and the toggle mutation rejects instead of resending /tunnel/start.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

vi.mock('@/api/client', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
}))

import * as apiClient from '@/api/client'
import { useSessionSharing } from '../useSessionSharing'

const mockGet = vi.mocked(apiClient.apiGet)
const mockPost = vi.mocked(apiClient.apiPost)

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

beforeEach(() => {
  mockGet.mockReset()
  mockPost.mockReset()
})

describe('h8/618 tunnel status unconfirmed blocks start/stop', () => {
  it('marks status unconfirmed and rejects toggle when the status fetch fails', async () => {
    mockGet.mockRejectedValue(new Error('tunnel status down'))
    const { result } = renderHook(
      () => useSessionSharing({ matchId: null, tunnelProvider: 'cloudflare' } as never),
      { wrapper },
    )
    await waitFor(() => expect(result.current.tunnelUnconfirmed).toBe(true))
    await act(async () => {
      await expect(result.current.tunnelToggle.mutateAsync()).rejects.toThrow()
    })
    expect(mockPost).not.toHaveBeenCalled()
  })
})
