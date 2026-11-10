/**
 * 最低標本数は描画の前に判定する (監査 #438)。
 * 1〜4 リターンでは結果の表を出さず、5 リターン以上で出す。値は架空。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { hasSufficientSample } from '@/utils/sampleGate'

vi.mock('@/api/client', () => ({
  apiGet: vi.fn(),
}))

import * as apiClient from '@/api/client'
import { FirstReturnAnalysis } from '../FirstReturnAnalysis'

const mockApi = vi.mocked(apiClient.apiGet)

function response(sampleSize: number) {
  return {
    success: true,
    data: {
      zones: [{ zone: 'BC', count: sampleSize, freq_rate: 1, win_rate: 0.5 }],
      top_zones: ['BC'],
      sample_size: sampleSize,
    },
    meta: { sample_size: sampleSize, confidence: { level: 'low', stars: '', label: '' } },
  }
}

function renderCard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <FirstReturnAnalysis playerId={1} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  mockApi.mockReset()
})

describe('hasSufficientSample', () => {
  it('is false below the minimum and true at or above it', () => {
    expect(hasSufficientSample(0, 3)).toBe(false)
    expect(hasSufficientSample(2, 3)).toBe(false)
    expect(hasSufficientSample(3, 3)).toBe(true)
    expect(hasSufficientSample(Number.NaN, 3)).toBe(false)
  })
})

describe('FirstReturnAnalysis minimum sample', () => {
  it('does not show the result table at n=2', async () => {
    mockApi.mockResolvedValue(response(2) as never)
    const { container } = renderCard()
    await waitFor(() => expect(mockApi).toHaveBeenCalled())
    // 応答の反映を待ってから (旧実装ならこの間に表が出る) 表が無いことを確かめる
    await new Promise((resolve) => setTimeout(resolve, 100))
    expect(container.querySelector('table')).toBeNull()
  })

  it('shows the result table at n=5', async () => {
    mockApi.mockResolvedValue(response(5) as never)
    const { container } = renderCard()
    await waitFor(() => expect(container.querySelector('table')).not.toBeNull())
  })
})
