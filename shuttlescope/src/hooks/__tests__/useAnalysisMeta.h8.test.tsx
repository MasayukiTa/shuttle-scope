/**
 * h8 item 624: evidence-meta governance must fail closed. When the meta fetch
 * fails, isOnHold must return true (treat as hold) rather than fail-open false.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

vi.mock('@/api/client', () => ({
  apiGet: vi.fn(),
}))

import * as apiClient from '@/api/client'
import { useAnalysisMeta } from '../useAnalysisMeta'

const mockApi = vi.mocked(apiClient.apiGet)

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

beforeEach(() => {
  mockApi.mockReset()
})

describe('h8/624 useAnalysisMeta fail-closed on fetch error', () => {
  it('isOnHold returns true for any type when the meta fetch fails', async () => {
    mockApi.mockRejectedValue(new Error('meta down'))
    const { result } = renderHook(() => useAnalysisMeta(), { wrapper })
    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.isOnHold('epv_state')).toBe(true)
  })

  it('isOnHold reflects override_status when the meta fetch succeeds', async () => {
    mockApi.mockResolvedValue({
      success: true,
      data: [{ analysis_type: 'epv_state', override_status: 'approved' }],
    } as never)
    const { result } = renderHook(() => useAnalysisMeta(), { wrapper })
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.isOnHold('epv_state')).toBe(false)
  })
})
