/**
 * 監査 #744: RecommendationRanking の成功状態の見出しと NoData 単位が
 * t() 経由で出ることを固定する。以前は成功状態だけ
 * 「推奨アドバイスランキング」 / unit="ストローク」を直書きしており、
 * 英語 UI でも日本語が残っていた。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ja from '@/i18n/ja.json'
import en from '@/i18n/en.json'

type Dict = Record<string, unknown>
function lookup(dict: Dict, key: string): string {
  const v = key.split('.').reduce<unknown>((o, k) => (o as Dict | undefined)?.[k], dict)
  return typeof v === 'string' ? v : key
}

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => lookup(en as Dict, key),
  }),
}))

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ role: 'analyst' }),
}))

vi.mock('@/api/client', () => ({
  apiGet: vi.fn(),
  API_BASE_URL: '',
}))

import * as apiClient from '@/api/client'
import { RecommendationRanking } from '../RecommendationRanking'

const mockApi = vi.mocked(apiClient.apiGet)

const RESP_EMPTY = {
  success: true,
  data: { items: [] },
  meta: { sample_size: 0 },
}

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  mockApi.mockReset()
  mockApi.mockResolvedValue(RESP_EMPTY as never)
})

describe('RecommendationRanking i18n (#744)', () => {
  it('成功状態の見出しが t() 経由で英語になる', async () => {
    const { container } = wrap(<RecommendationRanking playerId={1} />)
    await waitFor(() =>
      expect(container.textContent).toContain('Recommended advice ranking'),
    )
    expect(container.textContent).not.toContain('推奨アドバイスランキング')
    expect(container.textContent).not.toContain('ストローク')
  })

  it('k3 / k4 キーが ja / en 両方にある', () => {
    for (const dict of [ja, en] as Dict[]) {
      expect(lookup(dict, 'auto.RecommendationRanking.k3')).not.toBe('auto.RecommendationRanking.k3')
      expect(lookup(dict, 'auto.RecommendationRanking.k4')).not.toBe('auto.RecommendationRanking.k4')
    }
  })
})
