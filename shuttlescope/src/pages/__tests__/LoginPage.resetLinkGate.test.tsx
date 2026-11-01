/**
 * LoginPage: パスワードリセット導線が PASSWORD_RESET_ENABLED と連動する (監査 #504)。
 * 無効時はリンクを出さず、代わりに問い合わせ案内文を表示して行き止まりにしない。
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'

vi.mock('@/hooks/useAuth', () => ({ useAuth: () => ({ setSession: vi.fn() }) }))

const resetFlag = vi.hoisted(() => ({ value: false }))
vi.mock('@/utils/passwordReset', () => ({
  get PASSWORD_RESET_ENABLED() {
    return resetFlag.value
  },
}))

import { LoginPage } from '../LoginPage'

afterEach(() => {
  cleanup()
})

describe('LoginPage password reset link gating (#504)', () => {
  it('無効時はリセットリンクを出さず案内文を表示する', () => {
    resetFlag.value = false
    render(<LoginPage onLogin={() => {}} />)
    expect(document.querySelector('a[href="#/password/reset"]')).toBeNull()
    expect(screen.getByText(/停止中|contact/i)).toBeTruthy()
  })

  it('有効時はリセットリンクを表示する', () => {
    resetFlag.value = true
    render(<LoginPage onLogin={() => {}} />)
    expect(document.querySelector('a[href="#/password/reset"]')).not.toBeNull()
  })
})
