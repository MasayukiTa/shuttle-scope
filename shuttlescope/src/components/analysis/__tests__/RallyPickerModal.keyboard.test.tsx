/**
 * ラリー地点選択モーダル: グラフの点クリックに頼らず、select + ボタンで選べること (キーボード代替)。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ role: 'coach' }),
}))

vi.mock('@/api/client', () => ({
  apiGet: vi.fn(),
  API_BASE_URL: '',
}))

import * as apiClient from '@/api/client'
import { RallyPickerModal } from '../RallyPickerModal'

class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}
;(globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = RO

const mockApi = vi.mocked(apiClient.apiGet)

const sets = [
  {
    set_id: 1, set_num: 1, momentum_changes: [],
    rallies: [
      { rally_num: 1, score_a: 1, score_b: 0, winner: 'a', point_diff: 1 },
      { rally_num: 2, score_a: 1, score_b: 1, winner: 'b', point_diff: 0 },
      { rally_num: 3, score_a: 2, score_b: 1, winner: 'a', point_diff: 1 },
    ],
  },
]

function renderModal(onSelect = vi.fn(), onClose = vi.fn()) {
  mockApi.mockResolvedValue({ success: true, data: { sets } } as never)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <RallyPickerModal
        matchId={1}
        matchLabel="m"
        initialSet={1}
        selectedRallyNum={null}
        onSelect={onSelect}
        onClear={vi.fn()}
        onClose={onClose}
      />
    </QueryClientProvider>,
  )
  return { onSelect, onClose }
}

beforeEach(() => {
  mockApi.mockReset()
})

describe('RallyPickerModal keyboard alternative', () => {
  it('selects a rally through a labelled select and a confirm button', async () => {
    const { onSelect, onClose } = renderModal()

    const select = await waitFor(() => screen.getByRole('combobox'))
    expect(select.id).not.toBe('')
    expect(document.querySelector(`label[for="${select.id}"]`)).not.toBeNull()

    // 選ぶ前は確定できない。選んだだけでは onSelect は呼ばれない (矢印キーの移動で閉じないため)
    const confirm = select.parentElement?.querySelector('button') as HTMLButtonElement
    expect(confirm.disabled).toBe(true)
    fireEvent.change(select, { target: { value: '2' } })
    expect(onSelect).not.toHaveBeenCalled()
    expect(confirm.disabled).toBe(false)

    fireEvent.click(confirm)
    expect(onSelect).toHaveBeenCalledWith(1, 2)
    expect(onClose).toHaveBeenCalled()
  })
})
