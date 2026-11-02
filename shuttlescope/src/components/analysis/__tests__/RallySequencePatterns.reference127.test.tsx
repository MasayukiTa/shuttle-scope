/**
 * 監査 #127: ラリー3連ショットパターンで、出現回数が少ない個別パターンは
 * 「参考値」と明示する。セクション全体の総球数を根拠に個別パターンまで
 * 高信頼に見せない。
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const resp = {
  success: true,
  data: {
    win_sequences: [
      { sequence: ['a', 'b', 'c'], labels: ['LOWN_WIN'], count: 6, win_rate: 1.0, win_count: 6, ci_low: 0.6, ci_high: 1.0 },
    ],
    loss_sequences: [
      { sequence: ['d', 'e', 'f'], labels: ['HIGHN_LOSS'], count: 50, win_rate: 0.3, win_count: 15, ci_low: 0.2, ci_high: 0.42 },
    ],
    total_rallies: 120,
    eligible_rallies: 100,
    baseline_win_rate: 0.5,
  },
  meta: { sample_size: 35669 },
}

vi.mock('@/api/client', () => ({
  API_BASE_URL: 'http://localhost',
  apiGet: vi.fn().mockImplementation(() => Promise.resolve(resp)),
}))

import { RallySequencePatterns } from '../RallySequencePatterns'

function renderCard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <RallySequencePatterns playerId={1} />
    </QueryClientProvider>,
  )
}

describe('RallySequencePatterns reference-value badge (audit #127)', () => {
  it('marks a low-occurrence pattern as a reference value', async () => {
    renderCard()
    await waitFor(() => {
      expect(screen.getByText('LOWN_WIN')).toBeTruthy()
    })
    expect(screen.getByText('参考値')).toBeTruthy()
  })

  it('does not mark a high-occurrence pattern as a reference value', async () => {
    renderCard()
    await waitFor(() => {
      expect(screen.getByText('HIGHN_LOSS')).toBeTruthy()
    })
    expect(screen.getAllByText('参考値').length).toBe(1)
  })
})
