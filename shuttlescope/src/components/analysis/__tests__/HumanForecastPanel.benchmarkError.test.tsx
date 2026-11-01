import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

// BenchmarkSection \u306e /prediction/benchmark/:id \u53d6\u5f97\u5931\u6557\u3092\n// \u300c\u5b9f\u7e3e\u30c7\u30fc\u30bf\u306a\u3057\u300d\u3068\u533a\u5225\u3059\u308b (item #608)\u3002
const apiGet = vi.fn()
vi.mock('@/api/client', () => ({
  apiGet: (...a: unknown[]) => apiGet(...a),
  apiPost: vi.fn(),
  apiDelete: vi.fn(),
  newIdempotencyKey: () => 'k',
}))
vi.mock('@/hooks/useIsLightMode', () => ({ useIsLightMode: () => false }))
vi.mock('@/hooks/useAuth', () => ({ useAuth: () => ({ userId: 1, role: 'coach' }) }))

import { HumanForecastPanel } from '../HumanForecastPanel'

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <HumanForecastPanel matchId={7} playerId={3} />
    </QueryClientProvider>,
  )
}

describe('HumanForecastPanel BenchmarkSection fetch failure', () => {
  beforeEach(() => {
    apiGet.mockReset()
  })

  it('#608: shows a retryable error instead of benchmark_no_data when the request fails', async () => {
    apiGet.mockImplementation((path: string) => {
      if (typeof path === 'string' && path.startsWith('/prediction/human_forecast/')) {
        return Promise.resolve({ success: true, data: [] })
      }
      if (typeof path === 'string' && path.startsWith('/prediction/benchmark/')) {
        return Promise.reject(new Error('500'))
      }
      return Promise.resolve({ success: true, data: [] })
    })
    const { container } = renderPanel()
    // \u30d9\u30f3\u30c1\u30de\u30fc\u30af\u30bb\u30af\u30b7\u30e7\u30f3\u3092\u958b\u304f (\u6298\u308a\u305f\u305f\u307f\u30c8\u30b0\u30eb\u30dc\u30bf\u30f3)
    const toggles = Array.from(container.querySelectorAll('button')).filter(
      (b) => (b.textContent ?? '').includes('\u30d9\u30f3\u30c1\u30de\u30fc\u30af'),
    )
    expect(toggles.length).toBeGreaterThan(0)
    fireEvent.click(toggles[toggles.length - 1])
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('\u53d6\u5f97\u3067\u304d\u307e\u305b\u3093\u3067\u3057\u305f')
    expect(screen.queryByText(/\u30d9\u30f3\u30c1\u30de\u30fc\u30af\u30c7\u30fc\u30bf\u306a\u3057/)).toBeNull()
  })

  it('#608: shows benchmark_no_data on a successful zero-forecast response', async () => {
    apiGet.mockImplementation((path: string) => {
      if (typeof path === 'string' && path.startsWith('/prediction/human_forecast/')) {
        return Promise.resolve({ success: true, data: [] })
      }
      if (typeof path === 'string' && path.startsWith('/prediction/benchmark/')) {
        return Promise.resolve({ success: true, data: { summary: [], match_comparisons: [], total_forecasts: 0 } })
      }
      return Promise.resolve({ success: true, data: [] })
    })
    const { container } = renderPanel()
    const toggles = Array.from(container.querySelectorAll('button')).filter(
      (b) => (b.textContent ?? '').includes('\u30d9\u30f3\u30c1\u30de\u30fc\u30af'),
    )
    fireEvent.click(toggles[toggles.length - 1])
    await waitFor(() => expect(screen.getByText(/\u30d9\u30f3\u30c1\u30de\u30fc\u30af\u30c7\u30fc\u30bf\u306a\u3057/)).toBeTruthy())
    expect(screen.queryByRole('alert')).toBeNull()
  })
})
