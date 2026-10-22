/**
 * 質問票回答は選手本人の主観データ。履歴詳細モーダルは analyst / admin にも読み取り専用で、
 * 回答を書き換える select と保存ボタンを出さない。
 */
import { describe, it, expect, vi } from 'vitest'
import { render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ja from '@/i18n/ja.json'

type Dict = Record<string, unknown>
function lookup(dict: Dict, key: string): string {
  const v = key.split('.').reduce<unknown>((o, k) => (o as Dict | undefined)?.[k], dict)
  return typeof v === 'string' ? v : key
}

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => lookup(ja as Dict, key),
  }),
}))
vi.mock('@/hooks/useAuth', () => ({ useAuth: () => ({ role: 'admin' }) }))
vi.mock('@/api/client', () => ({
  apiDelete: vi.fn(),
  newIdempotencyKey: () => 'k',
}))

import { HistoryDetailModal } from '../HistoryDetailModal'

describe('HistoryDetailModal', () => {
  it('shows questionnaire answers read-only even for admin', () => {
    const record = {
      id: 7,
      measured_at: '2026-10-01',
      condition_type: 'weekly',
      questionnaire_json: JSON.stringify({ q1: 3, q2: 5 }),
    }
    const { container, queryByText } = render(
      <QueryClientProvider client={new QueryClient()}>
        <HistoryDetailModal record={record} isLight onClose={() => {}} />
      </QueryClientProvider>,
    )
    expect(container.querySelectorAll('select').length).toBe(0)
    expect(queryByText(lookup(ja as Dict, 'condition.history_detail.close'))).not.toBeNull()
    expect(container.textContent).toContain('q1')
    expect(container.textContent).toContain('5')
  })
})
