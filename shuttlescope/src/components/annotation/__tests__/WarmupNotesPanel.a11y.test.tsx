import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

import { WarmupNotesPanel } from '../WarmupNotesPanel'
import * as apiClient from '@/api/client'

vi.mock('@/api/client', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
}))

const props = {
  matchId: 7,
  playerAId: 1,
  playerBId: 2,
  playerAName: 'A',
  playerBName: 'B',
  locked: false,
  onClose: vi.fn(),
}

// #531: 単一選択の観察値/確信度ボタンが支援技術へ radiogroup + radio + aria-checked で
// 伝わることを固定する。以前は通常 Button のみで選択状態もグループ文脈も無かった。
describe('WarmupNotesPanel accessibility (radiogroup semantics)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(apiClient.apiGet).mockResolvedValue({ success: true, data: [] })
  })

  it('exposes each single-select observation group as a radiogroup of radios', async () => {
    render(<WarmupNotesPanel {...props} />)

    // 読込完了まで待つ (ready になると保存ボタンが有効)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^保存/ })).toBeEnabled()
    })

    // 観察項目ごとに radiogroup が生成される (値グループ + 確信度グループ)
    const groups = screen.getAllByRole('radiogroup')
    expect(groups.length).toBeGreaterThan(0)

    // 各 radiogroup には少なくとも 1 つの role=radio が含まれる
    const radios = screen.getAllByRole('radio')
    expect(radios.length).toBeGreaterThan(0)

    // 初期状態ではどの radio も aria-checked=false (未選択) で描画される
    for (const r of radios) {
      expect(r).toHaveAttribute('aria-checked')
    }
  })

  it('reflects the selected value via aria-checked=true after a click', async () => {
    const { default: userEvent } = await import('@testing-library/user-event')
    const user = userEvent.setup()
    render(<WarmupNotesPanel {...props} />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^保存/ })).toBeEnabled()
    })

    const radios = screen.getAllByRole('radio')
    const target = radios.find((r) => r.getAttribute('aria-checked') === 'false')
    expect(target).toBeDefined()

    await user.click(target!)
    expect(target!).toHaveAttribute('aria-checked', 'true')
  })
})
