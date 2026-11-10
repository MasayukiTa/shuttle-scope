/**
 * Audit #185: the transition matrix masks the diagonal (self-transition). The
 * reason must be shown on screen, not left implicit. We assert the diagonal
 * explanation note is rendered.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const resp = {
  data: {
    matrix: [[0.0, 0.5], [0.5, 0.0]],
    shot_labels: ['Clear', 'Smash'],
    shot_keys: ['clear', 'smash'],
    raw_counts: [[0, 3], [2, 0]],
    total_transitions: 5,
    rallies_in_scope: 3,
    rallies_total: 4,
    top_sequences: [],
  },
  meta: { sample_size: 5, confidence: { level: 'low', stars: '*', label: 'low' } },
}

vi.mock('@/api/client', () => ({
  API_BASE_URL: 'http://localhost',
  apiGet: vi.fn().mockImplementation(() => Promise.resolve(resp)),
}))

import { TransitionMatrix } from '../TransitionMatrix'

function renderCard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <TransitionMatrix playerId={1} />
    </QueryClientProvider>,
  )
}

describe('TransitionMatrix diagonal note (audit #185)', () => {
  it('explains why the diagonal is masked', async () => {
    renderCard()
    // 注記は凡例と本文の両方に「対角線」を含む（複数要素）
    await waitFor(() => {
      expect(screen.getAllByText(/対角線/).length).toBeGreaterThanOrEqual(2)
    })
    // 本文の説明文（「隠しています」）が出る
    expect(screen.getByText(/隠しています/)).toBeTruthy()
  })
})
