/**
 * 推奨アドバイスランキング: player には勝率ベースの内容を一切見せない
 *
 * 製品ルール (CLAUDE.md): player 向け画面に勝率の判定・弱点表現を見せない。
 * 以前は本文の「勝率」を「活躍率」へ置換していたが、同じ指標の別名になるだけだったため、
 * player ロールでは取得も描画もしない。analyst / coach / admin の表示は従来どおり。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { UserRole } from '@/types'

let mockRole: UserRole | null = 'player'

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ role: mockRole }),
}))

vi.mock('@/api/client', () => ({
  apiGet: vi.fn(),
  API_BASE_URL: '',
}))

import * as apiClient from '@/api/client'
import { RecommendationRanking } from '../RecommendationRanking'

const mockApi = vi.mocked(apiClient.apiGet)

const RESP = {
  success: true,
  data: {
    items: [
      {
        rank: 1,
        category: 'shot',
        title: 'クロスは勝率が高い傾向',
        body: 'クロスの勝率は 70% です',
        priority_score: 0.8,
        sample_size: 30,
        confidence_level: 'medium',
        win_rate: 0.7,
      },
    ],
  },
  meta: { sample_size: 30, confidence: { level: 'medium', stars: '★★', label: 'medium' } },
}

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  mockApi.mockReset()
  mockApi.mockResolvedValue(RESP as never)
  mockRole = 'player'
})

describe('RecommendationRanking', () => {
  it('player: 何も描かず、ランキングを取得もしない', async () => {
    const { container } = wrap(<RecommendationRanking playerId={1} />)
    await new Promise((r) => setTimeout(r, 20))
    expect(container.textContent).toBe('')
    expect(mockApi).not.toHaveBeenCalled()
  })

  it.each(['analyst', 'coach', 'admin'] as UserRole[])('%s: 従来どおり本文を描く', async (r) => {
    mockRole = r
    const { container } = wrap(<RecommendationRanking playerId={1} />)
    await waitFor(() => expect(container.textContent).toContain('クロスは勝率が高い傾向'))
    expect(container.textContent).not.toContain('活躍率')
  })
})
