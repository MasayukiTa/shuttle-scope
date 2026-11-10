import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

// \u8a66\u5408\u4e00\u89a7 (/v1/expert/videos) \u3068 CoG \u89e3\u6790 (/v1/analysis/cog) \u306e\n// \u53d6\u5f97\u5931\u6557\u3092\u7a7a\u72b6\u614b\u3068\u533a\u5225\u3059\u308b (item #605 / #607)\u3002
const apiGet = vi.fn()
vi.mock('@/api/client', () => ({
  apiGet: (...a: unknown[]) => apiGet(...a),
}))
vi.mock('@/components/analysis/CoGTimeline', () => ({
  CoGTimeline: () => null,
}))

import { CoGDetectionPage } from '../CoGDetectionPage'

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <CoGDetectionPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('CoGDetectionPage fetch failures', () => {
  beforeEach(() => {
    apiGet.mockReset()
  })

  it('#605: shows a retryable error for the match list instead of a silent empty select', async () => {
    apiGet.mockImplementation((path: string) => {
      if (path === '/v1/expert/videos') return Promise.reject(new Error('500'))
      return Promise.resolve([])
    })
    renderPage()
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('\u8a66\u5408\u4e00\u89a7\u3092\u8aad\u307f\u8fbc\u3081\u307e\u305b\u3093\u3067\u3057\u305f')
    expect(screen.getByRole('button', { name: '\u518d\u8a66\u884c' })).toBeTruthy()
  })

  it('#605: no match-list error on a successful empty list', async () => {
    apiGet.mockImplementation(() => Promise.resolve([]))
    renderPage()
    await waitFor(() => expect(apiGet).toHaveBeenCalled())
    expect(screen.queryByText(/\u8a66\u5408\u4e00\u89a7\u3092\u8aad\u307f\u8fbc\u3081\u307e\u305b\u3093\u3067\u3057\u305f/)).toBeNull()
  })

  it('#607: shows a retryable CoG error instead of no-data when the analysis request fails', async () => {
    apiGet.mockImplementation((path: string) => {
      if (path === '/v1/expert/videos') return Promise.resolve([{ match_id: 1, title: 'M1' }])
      if (path === '/v1/expert/clips') return Promise.resolve({ clips: [{ stroke_id: 11, rally_context: {} }] })
      if (path === '/v1/analysis/cog') return Promise.reject(new Error('500'))
      return Promise.resolve([])
    })
    const { container } = renderPage()
    const matchSelect = await waitFor(() => {
      const el = container.querySelector('#cog-match-select') as HTMLSelectElement | null
      if (!el || el.querySelectorAll('option').length < 2) throw new Error('matches not loaded')
      return el
    })
    fireEvent.change(matchSelect, { target: { value: '1' } })
    const strokeSelect = await waitFor(() => {
      const el = container.querySelector('#cog-stroke-select') as HTMLSelectElement | null
      if (!el || el.querySelectorAll('option').length < 2) throw new Error('clips not loaded')
      return el
    })
    fireEvent.change(strokeSelect, { target: { value: '11' } })
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('\u30c7\u30fc\u30bf\u3092\u53d6\u5f97\u3067\u304d\u307e\u305b\u3093\u3067\u3057\u305f')
    expect(screen.queryByText('\u3053\u306e\u30b9\u30c8\u30ed\u30fc\u30af\u306e\u91cd\u5fc3\u30c7\u30fc\u30bf\u304c\u3042\u308a\u307e\u305b\u3093')).toBeNull()
  })
})
