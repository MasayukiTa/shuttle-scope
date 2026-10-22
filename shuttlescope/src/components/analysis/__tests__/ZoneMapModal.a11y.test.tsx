/**
 * ゾーン詳細モーダル: dialog として公開し、選択状態を支援技術へ伝える
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ role: 'coach' }),
}))

vi.mock('@/api/client', () => ({
  apiGet: vi.fn(async () => ({ success: true, data: null, meta: {} })),
  API_BASE_URL: '',
}))

import { DEFAULT_FILTERS } from '@/types'
import { ZoneMapModal } from '../ZoneMapModal'

function wrap(onClose: () => void) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ZoneMapModal
        type="vulnerability"
        playerId={1}
        filters={DEFAULT_FILTERS}
        vulnZoneData={{ BR: { loss_count: 3, total_count: 10, loss_rate: 0.3 } }}
        sampleSize={10}
        onClose={onClose}
      />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  document.body.innerHTML = ''
})

describe('ZoneMapModal accessibility', () => {
  it('role=dialog / aria-modal / 見出しで名前が付く', () => {
    wrap(() => {})
    const dialog = screen.getByRole('dialog')
    expect(dialog.getAttribute('aria-modal')).toBe('true')
    expect(dialog.getAttribute('aria-labelledby')).toBeTruthy()
    expect(screen.getByRole('dialog', { name: /ゾーン詳細/ })).toBe(dialog)
  })

  it('開いたらフォーカスがダイアログへ移り、Esc で閉じる', () => {
    const onClose = vi.fn()
    wrap(onClose)
    const dialog = screen.getByRole('dialog')
    expect(document.activeElement).toBe(dialog)
    fireEvent.keyDown(dialog, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('ゾーンボタンの選択状態を aria-pressed で返す', () => {
    wrap(() => {})
    const buttons = screen.getAllByRole('button', { pressed: false })
    const zone = buttons.find((b) => (b.textContent ?? '').includes('奥右'))
    expect(zone).toBeTruthy()
    fireEvent.click(zone as HTMLElement)
    const pressed = screen.getAllByRole('button', { pressed: true })
    expect(pressed).toHaveLength(1)
    expect(pressed[0].textContent).toContain('奥右')
  })
})
