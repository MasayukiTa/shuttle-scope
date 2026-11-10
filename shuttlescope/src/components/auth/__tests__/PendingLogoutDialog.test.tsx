/**
 * G4 #529: 未送信ラリーがあるままのログアウト確認ダイアログ。
 * delete は 2 段確認、send 失敗時はエラー表示してダイアログを閉じない。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

import { PendingLogoutDialog } from '../PendingLogoutDialog'

describe('PendingLogoutDialog', () => {
  let onSend: ReturnType<typeof vi.fn<() => Promise<void>>>
  let onKeep: ReturnType<typeof vi.fn<() => void>>
  let onDelete: ReturnType<typeof vi.fn<() => Promise<void>>>
  let onCancel: ReturnType<typeof vi.fn<() => void>>

  beforeEach(() => {
    onSend = vi.fn<() => Promise<void>>().mockResolvedValue(undefined)
    onKeep = vi.fn<() => void>()
    onDelete = vi.fn<() => Promise<void>>().mockResolvedValue(undefined)
    onCancel = vi.fn<() => void>()
  })

  function renderDialog() {
    return render(
      <PendingLogoutDialog
        pendingCount={3}
        onSend={onSend}
        onKeep={onKeep}
        onDelete={onDelete}
        onCancel={onCancel}
      />,
    )
  }

  it('send を押すと onSend が呼ばれる', async () => {
    renderDialog()
    fireEvent.click(screen.getByText('auth.pending_send'))
    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1))
  })

  it('keep は即座に onKeep を呼ぶ', () => {
    renderDialog()
    fireEvent.click(screen.getByText('auth.pending_keep'))
    expect(onKeep).toHaveBeenCalledTimes(1)
  })

  it('delete は 2 段確認: 1 回目は確認文言、onDelete は呼ばない', () => {
    renderDialog()
    fireEvent.click(screen.getByText('auth.pending_delete'))
    expect(onDelete).not.toHaveBeenCalled()
    // 確認文言に切り替わる
    expect(screen.getByText('auth.pending_delete_confirm')).toBeTruthy()
  })

  it('delete を 2 回押すと onDelete が呼ばれる', async () => {
    renderDialog()
    fireEvent.click(screen.getByText('auth.pending_delete'))
    fireEvent.click(screen.getByText('auth.pending_delete_confirm'))
    await waitFor(() => expect(onDelete).toHaveBeenCalledTimes(1))
  })

  it('send が reject したらエラーを出して閉じない (データ保持)', async () => {
    onSend = vi.fn<() => Promise<void>>().mockRejectedValue(new Error('network'))
    render(
      <PendingLogoutDialog
        pendingCount={3}
        onSend={onSend}
        onKeep={onKeep}
        onDelete={onDelete}
        onCancel={onCancel}
      />,
    )
    fireEvent.click(screen.getByText('auth.pending_send'))
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('auth.pending_error'))
  })

  it('cancel は onCancel を呼ぶ', () => {
    renderDialog()
    fireEvent.click(screen.getByText('auth.pending_cancel'))
    expect(onCancel).toHaveBeenCalledTimes(1)
  })
})
