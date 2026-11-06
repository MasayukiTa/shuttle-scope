import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from '@/i18n'

// item #649: HumanForecastPanel の /prediction/human_forecast/:id 取得失敗を
// 「登録済み予測 0 件」と区別し、明示的なエラー状態を出す。
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

const ONE_FORECAST = [
  {
    id: 1,
    match_id: 7,
    player_id: 3,
    forecaster_role: 'coach',
    forecaster_name: null,
    predicted_outcome: 'win',
    predicted_set_path: null,
    predicted_win_probability: null,
    confidence_level: null,
    notes: null,
    created_at: null,
    creator_user_id: 1,
  },
]

describe('HumanForecastPanel forecast list fetch failure', () => {
  beforeEach(() => {
    apiGet.mockReset()
  })

  it('#649: shows a retryable error instead of an empty list when the request fails', async () => {
    apiGet.mockImplementation((path: string) => {
      if (typeof path === 'string' && path.startsWith('/prediction/human_forecast/')) {
        return Promise.reject(new Error('500'))
      }
      return Promise.resolve({ success: true, data: [] })
    })
    renderPanel()
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain(i18n.t('common_ui.query_failed'))
    expect(screen.getByText(i18n.t('common_ui.query_retry'))).toBeTruthy()
  })

  it('#649: renders saved forecasts on a successful response', async () => {
    apiGet.mockImplementation((path: string) => {
      if (typeof path === 'string' && path.startsWith('/prediction/human_forecast/')) {
        return Promise.resolve({ success: true, data: ONE_FORECAST })
      }
      return Promise.resolve({ success: true, data: [] })
    })
    renderPanel()
    await waitFor(() => expect(screen.getAllByText('W').length).toBeGreaterThan(0))
    expect(screen.queryByText(i18n.t('common_ui.query_failed'))).toBeNull()
  })

  it('#649: does not show the fetch error on a successful zero-forecast response', async () => {
    apiGet.mockImplementation((path: string) => {
      if (typeof path === 'string' && path.startsWith('/prediction/human_forecast/')) {
        return Promise.resolve({ success: true, data: [] })
      }
      return Promise.resolve({ success: true, data: [] })
    })
    renderPanel()
    await waitFor(() => expect(apiGet).toHaveBeenCalled())
    expect(screen.queryByText(i18n.t('common_ui.query_failed'))).toBeNull()
  })
})
