/**
 * LoginPage: MFA キャンセル後に元のパスワードと「表示」状態を残さない (監査 #725)、
 * パスワード表示ボタンの title / aria-label が言語に従う (監査 #727)。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

vi.mock('@/hooks/useAuth', () => ({ useAuth: () => ({ setSession: vi.fn() }) }))

import i18n from '@/i18n'
import { LoginPage } from '../LoginPage'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function passwordInput(container: HTMLElement): HTMLInputElement {
  return container.querySelector('input[autocomplete="current-password"]') as HTMLInputElement
}

describe('LoginPage', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (String(url).includes('/auth/bootstrap-status')) {
          return jsonResponse({ has_admin: true, bootstrap_configured: true })
        }
        return jsonResponse({ mfa_required: true, mfa_token: 'tok-for-test' })
      }),
    )
  })

  afterEach(async () => {
    vi.unstubAllGlobals()
    await i18n.changeLanguage('ja')
  })

  it('MFA をキャンセルして戻るとパスワードが空で、非表示に戻っている', async () => {
    const { container } = render(<LoginPage onLogin={() => {}} />)
    fireEvent.change(screen.getByPlaceholderText('ログインIDを入力'), { target: { value: 'user1' } })
    fireEvent.change(passwordInput(container), { target: { value: 'typed-secret' } })
    // 表示をオンにしてから MFA へ進む
    fireEvent.click(screen.getByTitle('表示'))
    expect(passwordInput(container).type).toBe('text')

    fireEvent.click(screen.getByRole('button', { name: /ログイン/ }))
    const cancel = await screen.findByText('ログイン画面に戻る')
    fireEvent.click(cancel)

    await waitFor(() => expect(passwordInput(container)).not.toBeNull())
    expect(passwordInput(container).value).toBe('')
    expect(passwordInput(container).type).toBe('password')
  })

  it('英語 UI ではパスワード表示ボタンの title と aria-label が英語', async () => {
    await i18n.changeLanguage('en')
    render(<LoginPage onLogin={() => {}} />)
    const btn = screen.getByTitle('Show')
    expect(btn.getAttribute('aria-label')).toBe('Show password')
  })
})
