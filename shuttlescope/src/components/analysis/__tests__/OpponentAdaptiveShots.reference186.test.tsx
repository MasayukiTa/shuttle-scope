/**
 * Audit #186: opponent x shot effectiveness must mark small-sample rows as
 * reference values. The section-wide confidence badge (research tier) must not
 * bleed into individual opponent x shot cells that only have tens of strokes.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const resp = {
  success: true,
  data: {
    global_shot_winrates: {},
    opponents: [
      {
        opponent_id: 1,
        opponent_name: 'Opp One',
        match_count: 3,
        shot_effectiveness: [
          { shot_type: 'flick', shot_label: 'Flick', count: 41, win_rate: 0.6, lift: 0.1 },
          { shot_type: 'slice', shot_label: 'Slice', count: 12, win_rate: 0.5, lift: -0.05 },
        ],
      },
    ],
  },
  meta: { sample_size: 13162, confidence: { level: 'high', stars: '***', label: 'high' } },
}

vi.mock('@/api/client', () => ({
  API_BASE_URL: 'http://localhost',
  apiGet: vi.fn().mockImplementation(() => Promise.resolve(resp)),
}))

import { OpponentAdaptiveShots } from '../OpponentAdaptiveShots'

function renderCard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <OpponentAdaptiveShots playerId={1} />
    </QueryClientProvider>,
  )
}

describe('OpponentAdaptiveShots small-sample reference (audit #186)', () => {
  it('marks the low-sample row and shows the reference hint', async () => {
    renderCard()
    await waitFor(() => {
      expect(screen.getByText('Slice')).toBeTruthy()
    })
    // reference label (per-row) + hint line both contain the reference token
    expect(screen.getAllByText(/\u53c2\u8003\u5024/).length).toBeGreaterThan(0)
  })
})
