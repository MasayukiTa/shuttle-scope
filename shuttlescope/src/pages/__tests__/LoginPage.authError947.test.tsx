/**
 * LoginPage: 認証失敗 (401) メッセージが言語設定に従う (監査 #947)。
 * 英語モードで 401 のとき、日本語固定の 「IDもしくはパスワードが違います」
 * ではなく en.json の error_invalid_credentials が表示されることを検証する。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

vi.mock('@/hooks/useAuth', () => ({ useAuth: () => ({ setSession: vi.fn() }) }))

import i18n from '@/i18n'
import en from '@/i18n/en.json'
import ja from '@/i18n/ja.json'
import { LoginPage } from '../LoginPage'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('LoginPage auth error (#947)', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (String(url).includes('/auth/bootstrap-status')) {
          return jsonResponse({ has_admin: true, bootstrap_configured: true })
        }
        if (String(url).includes('/auth/login')) {
          return jsonResponse({ detail: 'invalid' }, 401)
        }
        return jsonResponse({})
      }),
    )
  })

  afterEach(async () => {
    vi.unstubAllGlobals()
    await i18n.changeLanguage('ja')
  })

  it('both locales define the new login error keys', () => {
    expect((en as Record<string, any>).auto.LoginPage.error_invalid_credentials).toBeTruthy()
    expect((ja as Record<string, any>).auto.LoginPage.error_invalid_credentials).toBeTruthy()
    expect((en as Record<string, any>).auto.LoginPage.error_login_failed).toBeTruthy()
    expect((ja as Record<string, any>).auto.LoginPage.error_login_failed).toBeTruthy()
  })

  it('401 で英語モードなら英語メッセージを出し、日本語固定文言を出さない', async () => {
    await i18n.changeLanguage('en')
    render(<LoginPage onLogin={() => {}} />)
    fireEvent.change(screen.getByPlaceholderText(i18n.t('auto.LoginPage.k2')), {
      target: { value: 'user1' },
    })
    const pwd = document.querySelector('input[autocomplete="current-password"]') as HTMLInputElement
    fireEvent.change(pwd, { target: { value: 'wrong-secret' } })
    fireEvent.click(screen.getByRole('button', { name: i18n.t('auth.login_button') }))
    await waitFor(() => {
      expect(screen.getByText('Incorrect ID or password')).toBeTruthy()
    })
    expect(screen.queryByText('IDもしくはパスワードが違います')).toBeNull()
  })
})
