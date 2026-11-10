/**
 * 監査 #138: 反事実ショット比較で代替ショットの勝率が 100% に縮退したとき、
 * UI がその値を「改善幅」として見せず、明示的な警告状態を出すことを固定する。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import en from '@/i18n/en.json'

type Dict = Record<string, unknown>
function lookup(dict: Dict, key: string): string {
  const v = key.split('.').reduce<unknown>((o, k) => (o as Dict | undefined)?.[k], dict)
  return typeof v === 'string' ? v : key
}

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      const s = lookup(en as Dict, key)
      if (opts && typeof opts.n !== 'undefined') return s.replace('{{n}}', String(opts.n))
      return s
    },
  }),
}))

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ role: 'analyst' }),
}))

vi.mock('@/components/common/RoleGuard', () => ({
  RoleGuard: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('@/contexts/ResearchBundleContext', () => ({
  useResearchBundleSlice: () => ({ slice: undefined, loading: false, provided: false }),
}))

vi.mock('@/api/client', () => ({
  apiGet: vi.fn(),
  API_BASE_URL: '',
}))

import * as apiClient from '@/api/client'
import { CounterfactualShots } from '../CounterfactualShots'

const mockApi = vi.mocked(apiClient.apiGet)

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

function respWith(choices: Array<{ shot_type: string; label: string; count: number; win_rate: number }>, recommended: string, supported: boolean, lift: number) {
  return {
    success: true,
    data: {
      comparisons: [
        {
          context_label: 'Smash return',
          prev_shot: 'smash',
          choices,
          recommended,
          recommendation_supported: supported,
          lift,
          interpretation: 'test interpretation',
        },
      ],
    },
    meta: { sample_size: 49, confidence: { level: 'research', stars: '*', label: 'research' } },
  }
}

beforeEach(() => {
  mockApi.mockReset()
})

describe('CounterfactualShots 縮退ガード (#138)', () => {
  it('代替ショットが 100% に縮退したとき改善幅を見せず警告を出す', async () => {
    mockApi.mockResolvedValue(
      respWith(
        [
          { shot_type: 'roundhead', label: 'Roundhead', count: 20, win_rate: 1.0 },
          { shot_type: 'clear', label: 'Clear', count: 29, win_rate: 0.35 },
        ],
        'roundhead',
        true,
        0.65,
      ) as never,
    )
    const { container } = wrap(<CounterfactualShots playerId={1} />)
    await waitFor(() => expect(container.textContent).toContain('Needs review (degenerate)'))
    // 改善幅バッジ (Observed gap) は出さない
    expect(container.textContent).not.toContain('Observed gap')
    // アコーディオンを開くと警告文が出る
    fireEvent.click(screen.getByText('Smash return'))
    await waitFor(() =>
      expect(container.textContent).toContain('cannot be treated as an improvement gap'),
    )
  })

  it('正常な差があり supported なら改善幅バッジを出す', async () => {
    mockApi.mockResolvedValue(
      respWith(
        [
          { shot_type: 'drop', label: 'Drop', count: 30, win_rate: 0.62 },
          { shot_type: 'clear', label: 'Clear', count: 28, win_rate: 0.40 },
        ],
        'drop',
        true,
        0.22,
      ) as never,
    )
    const { container } = wrap(<CounterfactualShots playerId={1} />)
    await waitFor(() => expect(container.textContent).toContain('Observed gap +22pt'))
    expect(container.textContent).not.toContain('Needs review (degenerate)')
  })

  it('全候補が同率なら縮退扱いとする', async () => {
    mockApi.mockResolvedValue(
      respWith(
        [
          { shot_type: 'drop', label: 'Drop', count: 30, win_rate: 0.5 },
          { shot_type: 'clear', label: 'Clear', count: 28, win_rate: 0.5 },
        ],
        'drop',
        true,
        0.0,
      ) as never,
    )
    const { container } = wrap(<CounterfactualShots playerId={1} />)
    await waitFor(() => expect(container.textContent).toContain('Needs review (degenerate)'))
    expect(container.textContent).not.toContain('Observed gap')
  })
})
