/**
 * RallyDetailBanner ストローク取得失敗の表示テスト (#643)
 *
 * stroke query が失敗した場合、「記録なし」(k3) ではなく
 * 明示的なエラー状態 (k3_error) と再試行ボタン (k3_retry) を表示することを確認する。
 * 「記録なし」(k3) は成功レスポンスで strokes.length === 0 のときだけに限定される。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RallyDetailBanner, type RallyPoint } from '../ScoreProgression'

vi.mock('@/api/client', () => ({
  apiGet: vi.fn(),
}))

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ role: 'coach' }),
}))

vi.mock('@/components/common/MIcon', () => ({
  MIcon: () => null,
}))

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

import * as apiClient from '@/api/client'

const mockApiGet = apiClient.apiGet as unknown as ReturnType<typeof vi.fn>

const RALLY: RallyPoint & { set_num: number } = {
  rally_num: 3,
  rally_id: 42,
  score_a: 5,
  score_b: 4,
  winner: 'player_a',
  server: 'player_a',
  end_type: 'smash_winner',
  rally_length: 7,
  point_diff: 1,
  set_num: 1,
}

function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

function renderBanner() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <RallyDetailBanner rally={RALLY} />
    </QueryClientProvider>
  )
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('RallyDetailBanner stroke fetch error (#643)', () => {
  it('shows explicit error state and retry on fetch failure, not the no-record text', async () => {
    mockApiGet.mockRejectedValue(new Error('network down'))
    renderBanner()
    await waitFor(() => {
      expect(screen.getByText('auto.ScoreProgression.k3_error')).toBeTruthy()
    })
    expect(screen.getByText('auto.ScoreProgression.k3_retry')).toBeTruthy()
    expect(screen.queryByText('auto.ScoreProgression.k3')).toBeNull()
  })

  it('refetches when the retry button is clicked', async () => {
    mockApiGet.mockRejectedValue(new Error('network down'))
    renderBanner()
    await waitFor(() => {
      expect(screen.getByText('auto.ScoreProgression.k3_retry')).toBeTruthy()
    })
    const callsBefore = mockApiGet.mock.calls.length
    fireEvent.click(screen.getByText('auto.ScoreProgression.k3_retry'))
    await waitFor(() => {
      expect(mockApiGet.mock.calls.length).toBeGreaterThan(callsBefore)
    })
  })

  it('shows the no-record text only when the request succeeds with empty strokes', async () => {
    mockApiGet.mockResolvedValue({ success: true, data: { rally_id: 42, strokes: [] } })
    renderBanner()
    await waitFor(() => {
      expect(screen.getByText('auto.ScoreProgression.k3')).toBeTruthy()
    })
    expect(screen.queryByText('auto.ScoreProgression.k3_error')).toBeNull()
  })

  it('renders strokes when the request succeeds with data', async () => {
    mockApiGet.mockResolvedValue({
      success: true,
      data: {
        rally_id: 42,
        strokes: [
          { stroke_num: 1, player: 'player_a', shot_type: 'serve', hit_zone: null, land_zone: null, shot_quality: null },
        ],
      },
    })
    renderBanner()
    await waitFor(() => {
      expect(screen.queryByText('auto.ScoreProgression.k3')).toBeNull()
    })
    expect(screen.queryByText('auto.ScoreProgression.k3_error')).toBeNull()
  })
})
