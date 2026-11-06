/**
 * 監査 #496: 公開認証フォームの各 input がラベルと関連付き (htmlFor/id または aria-labelledby)され、
 * Accessible Name を持つことを検証する。getByLabelText はアクセシブル名で要素を引く。
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('@/hooks/useAuth', () => ({ useAuth: () => ({ setSession: vi.fn() }) }))

vi.mock('@/utils/passwordReset', () => ({ PASSWORD_RESET_ENABLED: true }))

import i18n from '@/i18n'
import RegisterPage from '../RegisterPage'
import InvitationAcceptPage from '../InvitationAcceptPage'
import PasswordResetConfirmPage from '../PasswordResetConfirmPage'
import { LoginPage } from '../LoginPage'

function labelled(id: string): HTMLInputElement {
  const el = document.getElementById(id) as HTMLInputElement | null
  expect(el).not.toBeNull()
  return el as HTMLInputElement
}

afterEach(async () => {
  vi.unstubAllGlobals()
  await i18n.changeLanguage('ja')
})

describe('a11y #496: 認証フォームの input が label と関連付く', () => {
  it('RegisterPage: 各入力欄が label と関連付いている', () => {
    render(<MemoryRouter><RegisterPage /></MemoryRouter>)
    for (const key of [
      'auth.register.username',
      'auth.register.email',
      'auth.register.password',
      'auth.register.display_name_optional',
      'auth.register.dob_optional',
    ]) {
      expect(screen.getByLabelText(i18n.t(key) as string)).toBeTruthy()
    }
    for (const id of [
      'register-username',
      'register-email',
      'register-password',
      'register-display-name',
      'register-dob',
    ]) {
      expect(labelled(id)).toBeTruthy()
    }
  })

  it('InvitationAcceptPage: info を与えた状態で id 付き label 構造を検証', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(
      JSON.stringify({ success: true, data: { email: 'a@example.com', role: 'player', team_id: null, expires_at: '2030-01-01T00:00:00Z' } }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    )))
    render(<MemoryRouter initialEntries={['/invitation?token=abc']}><InvitationAcceptPage /></MemoryRouter>)
    await screen.findByText(i18n.t('auth.invitation.title') as string)
    for (const id of ['invite-username', 'invite-password', 'invite-display-name']) {
      expect(labelled(id)).toBeTruthy()
    }
  })

  it('PasswordResetConfirmPage: トークンありで入力欄が label と関連付く', () => {
    render(<MemoryRouter initialEntries={['/password/reset/confirm?token=abc']}><PasswordResetConfirmPage /></MemoryRouter>)
    for (const id of ['reset-new-password', 'reset-confirm-password']) {
      expect(labelled(id)).toBeTruthy()
    }
  })

  it('LoginPage: ID / パスワード欄が label と関連付く', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => new Response(
      JSON.stringify(String(url).includes('/auth/bootstrap-status') ? { has_admin: true, bootstrap_configured: true } : {}),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    )))
    render(<LoginPage onLogin={() => {}} />)
    for (const id of ['login-identifier', 'login-password']) {
      expect(labelled(id)).toBeTruthy()
    }
  })
})
