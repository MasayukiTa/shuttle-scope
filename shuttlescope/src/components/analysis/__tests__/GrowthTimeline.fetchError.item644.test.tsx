/**
 * Audit #644: GrowthTimeline must not convert a fetch failure into a
 * "insufficient sample" no-data state. The main query failing surfaces an
 * error alert; a partner-only failure must not fall through to an empty
 * pair-comparison chart but surface the partner fetch error instead.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

vi.mock('@/api/client', () => ({
  apiGet: vi.fn(),
}))

import * as apiClient from '@/api/client'
import { GrowthTimeline } from '../GrowthTimeline'

const mockApi = vi.mocked(apiClient.apiGet)

function renderWithClient(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>)
}

function okResponse() {
  return {
    success: true,
    data: {
      points: [
        { match_id: 1, date: '2026-01-01', value: 0.5, moving_avg: 0.5 },
        { match_id: 2, date: '2026-01-02', value: 0.6, moving_avg: 0.55 },
        { match_id: 3, date: '2026-01-03', value: 0.7, moving_avg: 0.6 },
      ],
      trend: 'improving' as const,
      trend_delta: 0.2,
    },
    meta: { sample_size: 3, confidence: { level: 'ok', stars: '***', label: 'high' } },
  }
}

beforeEach(() => {
  mockApi.mockReset()
})

describe('#644 GrowthTimeline fails closed on fetch error', () => {
  it('main query failure shows an error alert, not no-data', async () => {
    mockApi.mockRejectedValue(new Error('network down'))
    renderWithClient(<GrowthTimeline playerId={1} />)
    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy())
  })

  it('partner-only failure surfaces a partner error, not an empty pair chart', async () => {
    mockApi.mockImplementation((_url: string, params?: Record<string, unknown>) => {
      if (params && params.player_id === 2) {
        return Promise.reject(new Error('partner down'))
      }
      return Promise.resolve(okResponse())
    })
    renderWithClient(<GrowthTimeline playerId={1} partnerPlayerId={2} />)
    await waitFor(() => expect(screen.getAllByRole('alert').length).toBeGreaterThan(0))
  })
})
