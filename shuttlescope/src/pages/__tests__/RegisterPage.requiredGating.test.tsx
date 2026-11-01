/**
 * 公開新規登録: 必須項目が未入力の間は「登録する」を disabled にする (項目509)。
 * RegisterPage の label は htmlFor を持たないため input は type で選択する。
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import ja from '@/i18n/ja.json'

vi.mock('@/components/auth/TurnstileWidget', () => ({ TurnstileWidget: () => null }))
vi.mock('@/api/client', () => ({ apiPost: vi.fn() }))

import RegisterPage from '../RegisterPage'

const submitLabel = (ja as unknown as { auth: { register: Record<string, string> } }).auth.register.submit

function renderPage() {
  const utils = render(
    <MemoryRouter>
      <RegisterPage />
    </MemoryRouter>,
  )
  const root = utils.container
  return {
    ...utils,
    username: root.querySelector('#register-username') as HTMLInputElement,
    email: root.querySelector('#register-email') as HTMLInputElement,
    password: root.querySelector('#register-password') as HTMLInputElement,
  }
}

describe('RegisterPage required-field gating (項目509)', () => {
  it('disables submit while fields are empty', () => {
    renderPage()
    expect(screen.getByRole('button', { name: submitLabel })).toBeDisabled()
  })

  it('enables submit once username, email and password meet the rules', () => {
    const { username, email, password } = renderPage()
    fireEvent.change(username, { target: { value: 'alice' } })
    fireEvent.change(email, { target: { value: 'a@example.com' } })
    fireEvent.change(password, { target: { value: 'abcd1234' } })
    expect(screen.getByRole('button', { name: submitLabel })).toBeEnabled()
  })

  it('keeps submit disabled when password is too short', () => {
    const { username, email, password } = renderPage()
    fireEvent.change(username, { target: { value: 'alice' } })
    fireEvent.change(email, { target: { value: 'a@example.com' } })
    fireEvent.change(password, { target: { value: 'short' } })
    expect(screen.getByRole('button', { name: submitLabel })).toBeDisabled()
  })
})
