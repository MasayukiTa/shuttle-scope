/**
 * パスワード変更成功後は、失効済みのセッションを画面に残さず、
 * ローカルの認証状態を破棄してログイン画面へ戻す (監査 #689)。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const clearRole = vi.fn()
const navigate = vi.fn()
const authChangePassword = vi.fn()

vi.mock('@/hooks/useAuth', () => ({ useAuth: () => ({ clearRole }) }))
vi.mock('react-router-dom', () => ({ useNavigate: () => navigate }))
vi.mock('@/api/client', () => ({
  authChangePassword: (...args: unknown[]) => authChangePassword(...args),
}))
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))
vi.mock('@/components/common/MIcon', () => ({ MIcon: () => null }))

import { PasswordChangeCard } from '../PasswordChangeCard'

function fill(container: HTMLElement, current: string, next: string, confirm: string) {
  const inputs = container.querySelectorAll('input[type="password"]')
  fireEvent.change(inputs[0], { target: { value: current } })
  fireEvent.change(inputs[1], { target: { value: next } })
  fireEvent.change(inputs[2], { target: { value: confirm } })
  fireEvent.click(screen.getByRole('button'))
}

describe('PasswordChangeCard', () => {
  beforeEach(() => {
    clearRole.mockReset()
    navigate.mockReset()
    authChangePassword.mockReset()
  })

  it('clears the local session and returns to login after a successful change', async () => {
    authChangePassword.mockResolvedValue({ success: true })
    const { container } = render(<PasswordChangeCard isLight />)
    fill(container, 'dummy-current-pass', 'Dummy-New-Pass1!', 'Dummy-New-Pass1!')
    await waitFor(() => expect(clearRole).toHaveBeenCalledTimes(1))
    expect(navigate).toHaveBeenCalledWith('/login?password_changed=1', { replace: true })
  })

  it('keeps the session when the change fails', async () => {
    authChangePassword.mockRejectedValue(new Error('failed'))
    const { container } = render(<PasswordChangeCard isLight />)
    fill(container, 'dummy-current-pass', 'Dummy-New-Pass1!', 'Dummy-New-Pass1!')
    await waitFor(() => expect(authChangePassword).toHaveBeenCalled())
    await waitFor(() => expect(container.textContent).toContain('failed'))
    expect(clearRole).not.toHaveBeenCalled()
    expect(navigate).not.toHaveBeenCalled()
  })

  it('does not call the API when the confirmation does not match', async () => {
    const { container } = render(<PasswordChangeCard isLight />)
    fill(container, 'dummy-current-pass', 'Dummy-New-Pass1!', 'Different-Pass1!')
    await waitFor(() => expect(container.textContent).toContain('auth.password_change.mismatch'))
    expect(authChangePassword).not.toHaveBeenCalled()
    expect(clearRole).not.toHaveBeenCalled()
  })
})
