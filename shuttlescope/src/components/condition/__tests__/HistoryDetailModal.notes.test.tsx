/**
 * 履歴詳細モーダル:
 *  - 保存したけがメモ・自由記述を、サーバが返したロールには表示する (#656)
 *  - 質問票の原回答フィールドが無い (本人向けレスポンス) ときは「回答なし」と誤表示しない (#654)
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
vi.mock('@/hooks/useAuth', () => ({ useAuth: () => ({ role: 'player' }) }))
vi.mock('@/api/client', () => ({
  apiDelete: vi.fn(),
  newIdempotencyKey: () => 'k',
}))

import { HistoryDetailModal } from '../HistoryDetailModal'

function renderModal(record: Record<string, unknown>) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <HistoryDetailModal record={record} isLight onClose={() => {}} />
    </QueryClientProvider>,
  )
}

describe('HistoryDetailModal notes and questionnaire section', () => {
  it('shows saved injury notes and free comment when the server returned them', () => {
    const { container } = renderModal({
      id: 1,
      measured_at: '2026-10-01',
      condition_type: 'weekly',
      injury_notes: 'left ankle taping',
      general_comment: 'slept badly',
    })
    expect(container.textContent).toContain('left ankle taping')
    expect(container.textContent).toContain('slept badly')
  })

  it('does not claim "no responses" when the record has no questionnaire field', () => {
    const { container } = renderModal({ id: 2, measured_at: '2026-10-01', condition_type: 'weekly' })
    expect(container.textContent).not.toContain(lookup(ja as Dict, 'condition.history_detail.no_responses'))
  })

  it('still says no responses when the field exists but is empty', () => {
    const { container } = renderModal({
      id: 3,
      measured_at: '2026-10-01',
      condition_type: 'weekly',
      questionnaire_json: '{}',
    })
    expect(container.textContent).toContain(lookup(ja as Dict, 'condition.history_detail.no_responses'))
  })
})
