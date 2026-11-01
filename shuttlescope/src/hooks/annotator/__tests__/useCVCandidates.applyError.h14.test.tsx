/**
 * h14 item 601: CV candidate apply / review must surface failures and must not
 * leave a stale "N applied" success after a later apply fails.
 *   - a failed apply clears the previous applyResult and sets applyError
 *   - starting a new apply clears the previous success before the request runs
 *   - a failed review-complete sets reviewError
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

vi.mock('@/api/client', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPut: vi.fn(),
}))

import * as apiClient from '@/api/client'
import { useCVCandidates } from '../useCVCandidates'

const mockGet = vi.mocked(apiClient.apiGet)
const mockPost = vi.mocked(apiClient.apiPost)
const mockPut = vi.mocked(apiClient.apiPut)

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

const applyOk = {
  success: true,
  data: {
    updated_strokes: 10,
    land_zone_count: 5,
    hit_zone_count: 3,
    hitter_count: 2,
    applied_by_mode: 'auto_filled',
    applied_fields: ['land_zone', 'hitter'],
  },
}

beforeEach(() => {
  mockGet.mockReset()
  mockPost.mockReset()
  mockPut.mockReset()
  // candidates + review-queue GETs: return empty-but-present payloads.
  mockGet.mockResolvedValue({ success: true, data: null } as never)
})

describe('h14/601 CV apply error + stale success', () => {
  it('clears the previous success and sets applyError when a later apply fails', async () => {
    mockPost.mockResolvedValueOnce(applyOk as never)
    const { result } = renderHook(() => useCVCandidates({ matchId: '42' }), { wrapper })

    await act(async () => {
      await result.current.applyCandidates('auto_filled', ['land_zone', 'hitter'])
    })
    await waitFor(() => expect(result.current.applyResult?.updated_strokes).toBe(10))
    expect(result.current.applyError).toBeNull()

    // Second apply fails: the "10 applied" must not remain.
    mockPost.mockRejectedValueOnce(new Error('boom'))
    await act(async () => {
      await result.current.applyCandidates('auto_filled', ['land_zone']).catch(() => {})
    })
    await waitFor(() => expect(result.current.applyError).not.toBeNull())
    expect(result.current.applyResult).toBeNull()
  })

  it('treats success=false as a failure and does not keep a result', async () => {
    mockPost.mockResolvedValueOnce({ success: false, data: null } as never)
    const { result } = renderHook(() => useCVCandidates({ matchId: '42' }), { wrapper })
    await act(async () => {
      await result.current.applyCandidates('auto_filled', ['hitter']).catch(() => {})
    })
    await waitFor(() => expect(result.current.applyError).not.toBeNull())
    expect(result.current.applyResult).toBeNull()
  })

  it('sets reviewError when marking a review item completed fails', async () => {
    mockPut.mockRejectedValueOnce(new Error('review down'))
    const { result } = renderHook(() => useCVCandidates({ matchId: '42' }), { wrapper })
    await act(async () => {
      await result.current.markReviewCompleted(7).catch(() => {})
    })
    await waitFor(() => expect(result.current.reviewError).not.toBeNull())
  })
})
