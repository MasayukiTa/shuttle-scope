/**
 * 監査 #145: 速報パネル内の信頼度表示は backend の meta.confidence 一本に統一される。
 *
 * 旧実装は ConfidenceBadge が unit="rallies"(閾値 60/250) で独自に再計算しており、
 * 38 ラリー(backend では descriptive_basic=medium, ★★☆) でも
 * バッジは「参考値（データ蓄積中）」を出す一方で、
 * 拡張ラベルは「★ 高確信度の追加示唆」と矛盾していた。
 * 本テストは backend の confidence(★★☆ / 中程度) がそのまま出て、
 * 「参考値（データ蓄積中）」も「高確信度」断言も出ないことを固定する。
 * 値は架空。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { UserRole } from '@/types'

let mockRole: UserRole | null = 'coach'

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    role: mockRole,
    hasRole: (allowed: UserRole[]) => (!mockRole ? false : mockRole === 'admin' ? true : allowed.includes(mockRole)),
  }),
}))

vi.mock('@/api/client', () => ({
  apiGet: vi.fn(),
  API_BASE_URL: '',
}))

import * as apiClient from '@/api/client'
import i18n from '@/i18n'
import { FlashAdvicePanel } from '../FlashAdvicePanel'

const mockApi = vi.mocked(apiClient.apiGet)

function mediumResponse() {
  // 38 ラリー: backend の descriptive_basic では level=medium, stars=★★☆。
  // backend が extended_items_included=true を返すのは confidence>=medium のとき。
  return {
    success: true,
    data: {
      items: [
        { category: 'opportunity', title: 'op', body: 'opbody', priority: 2 },
        { category: 'next_action', title: 'na', body: 'nabody', priority: 5 },
        { category: 'trend', title: 'tr', body: 'trbody', priority: 6 },
      ],
      item_count: 3,
      extended_items_included: true,
    },
    meta: {
      sample_size: 38,
      confidence: { level: 'medium', stars: '★★☆', label: '中程度（解釈に注意）', warning: null },
    },
  }
}

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <FlashAdvicePanel matchId={1} asOfSet={1} playerId={1} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  mockRole = 'coach'
  mockApi.mockReset()
})

describe('FlashAdvicePanel confidence system (item 145)', () => {
  it('medium 標本で backend の confidence.label を表示する', async () => {
    mockApi.mockResolvedValue(mediumResponse() as never)
    const { container } = renderPanel()
    await waitFor(() => expect(container.textContent).toContain('中程度（解釈に注意）'))
    expect(container.textContent).toContain('★★☆')
  })

  it('medium 標本で「参考値（データ蓄積中）」を出さない (FE 再計算の矛盾を除く)', async () => {
    mockApi.mockResolvedValue(mediumResponse() as never)
    const { container } = renderPanel()
    await waitFor(() => expect(mockApi).toHaveBeenCalled())
    await new Promise((resolve) => setTimeout(resolve, 100))
    expect(container.textContent || '').not.toContain('参考値（データ蓄積中）')
  })

  it('拡張項目があるときも「高確信度」と断言しない', async () => {
    mockApi.mockResolvedValue(mediumResponse() as never)
    const { container } = renderPanel()
    await waitFor(() => expect(container.textContent).toContain(i18n.t('analysis.flash.extended_note')))
    expect(container.textContent || '').not.toContain('高確信度')
  })
})
