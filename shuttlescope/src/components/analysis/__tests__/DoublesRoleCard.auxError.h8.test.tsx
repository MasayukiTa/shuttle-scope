/**
 * h8 item 617: DoublesRoleCard auxiliary sections (CV role / stability) must not
 * vanish silently when their queries fail. On a matches/CV fetch error an inline
 * QueryErrorNotice (role=alert) is shown instead of hiding the section.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

vi.mock('@/api/client', () => ({
  apiGet: vi.fn(),
}))

// Research bundle not provided -> component falls back to its own queries.
vi.mock('@/contexts/ResearchBundleContext', () => ({
  useResearchBundleSlice: () => ({ slice: undefined, loading: false, provided: false }),
}))

import * as apiClient from '@/api/client'
import { DoublesRoleCard } from '../DoublesRoleCard'

const mockApi = vi.mocked(apiClient.apiGet)

function renderCard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const ui = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
  return render(<DoublesRoleCard playerId={1} filters={{} as never} />, { wrapper: ui })
}

beforeEach(() => {
  mockApi.mockReset()
  mockApi.mockImplementation((path: string) => {
    if (path === '/matches') return Promise.reject(new Error('matches down'))
    if (path.includes('doubles_role_stability')) {
      return Promise.resolve({ success: true, data: { n_matches_analyzed: 0 }, meta: {} }) as never
    }
    if (path.includes('doubles_role')) {
      // roleData must have total_shots > 0 so the card body (and its aux
      // sections, where the error notice lives) actually renders.
      return Promise.resolve({
        success: true,
        data: {
          inferred_role: 'front',
          confidence_score: 0.8,
          front_ratio: 0.5,
          back_ratio: 0.3,
          neutral_ratio: 0.2,
          total_shots: 42,
          phase_breakdown: [],
          note: null,
        },
        meta: {},
      }) as never
    }
    return Promise.resolve({ success: true, data: {} }) as never
  })
}
)

describe('h8/617 DoublesRoleCard aux fetch error is surfaced', () => {
  it('renders an error alert when the matches query fails', async () => {
    renderCard()
    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy())
  })
})
