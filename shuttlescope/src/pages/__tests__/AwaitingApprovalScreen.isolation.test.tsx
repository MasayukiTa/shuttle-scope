/**
 * #345: 承認待ち (awaiting_admin_approval) ユーザはルートレベルで隔離され、
 * MainLayout や各ページではなく承認待ち専用の最小画面 (ログアウトボタン付き) のみを見る。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

const authLogout = vi.fn().mockResolvedValue(undefined)
const clearRole = vi.fn()

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>()
  return { ...actual, authLogout: (...a: unknown[]) => authLogout(...a) }
})
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ clearRole }),
}))

import { AwaitingApprovalScreen } from '../../App'

describe('AwaitingApprovalScreen (#345 route-level isolation)', () => {
  beforeEach(() => {
    authLogout.mockClear()
    clearRole.mockClear()
  })

  it('承認待ち専用の文言とログアウトボタンを表示する', () => {
    render(<AwaitingApprovalScreen />)
    expect(screen.getByText('仮登録の状態です')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'ログアウト' })).toBeInTheDocument()
  })

  it('生の i18n キーを画面に出さない', () => {
    const { container } = render(<AwaitingApprovalScreen />)
    expect(container.textContent || '').not.toMatch(/auth\.pending_approval\./)
  })

  it('MainLayout / サイドバーナビを描画しない (隔離)', () => {
    render(<AwaitingApprovalScreen />)
    // メインナビのランドマークである navigation ロールが存在しないことを確認。
    expect(screen.queryByRole('navigation')).toBeNull()
  })

  it('ログアウトボタンで authLogout と clearRole を呼ぶ', () => {
    render(<AwaitingApprovalScreen />)
    fireEvent.click(screen.getByRole('button', { name: 'ログアウト' }))
    expect(authLogout).toHaveBeenCalledTimes(1)
    expect(clearRole).toHaveBeenCalledTimes(1)
  })
})
