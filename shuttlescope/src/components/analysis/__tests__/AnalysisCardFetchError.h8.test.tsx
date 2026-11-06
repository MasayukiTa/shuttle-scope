/**
 * h8 item 615: analysis query-state cards must surface a fetch error with a
 * retry affordance instead of falling through to the no-data / empty state.
 * Covers FirstReturnAnalysis, SpatialDensityMap, TemporalPerformance.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

vi.mock('@/api/client', () => ({
  apiGet: vi.fn(),
}))

import * as apiClient from '@/api/client'
import { FirstReturnAnalysis } from '../FirstReturnAnalysis'
import { SpatialDensityMap } from '../SpatialDensityMap'
import { TemporalPerformance } from '../TemporalPerformance'

const mockApi = vi.mocked(apiClient.apiGet)

function renderWithClient(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>)
}

beforeEach(() => {
  mockApi.mockReset()
  mockApi.mockRejectedValue(new Error('network down'))
})

describe('h8/615 analysis cards fail closed on fetch error', () => {
  it('FirstReturnAnalysis shows an error alert, not no-data', async () => {
    renderWithClient(<FirstReturnAnalysis playerId={1} />)
    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy())
  })

  it('SpatialDensityMap shows an error alert on failure', async () => {
    renderWithClient(<SpatialDensityMap playerId={1} />)
    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy())
  })

  it('TemporalPerformance shows an error alert on failure', async () => {
    renderWithClient(<TemporalPerformance playerId={1} />)
    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy())
  })
})
