/**
 * LoginPage: パスワードリセット導線が PASSWORD_RESET_ENABLED と連動する (監査 #504)。
 * 無効時はリンクを出さず、代わりに問い合わせ案内文を表示して行き止まりにしない。
 */
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, cleanup, waitFor } from '@testing-library/react'
import i18n from '@/i18n'

vi.mock('@/hooks/useAuth', () => ({ useAuth: () => ({ setSession: vi.fn() }) }))

const resetFlag = vi.hoisted(() => ({ value: false }))
vi.mock('@/utils/passwordReset', () => ({
  get PASSWORD_RESET_ENABLED() {
    return resetFlag.value
  },
}))

import { LoginPage } from '../LoginPage'

// このスイートの flaky には 2 つの非同期レースが絡む:
//  (1) LoginPage は mount 時に fetchBootstrapStatus() -> fetch(bootstrap-status)
//      を呼ぶ。モックしないと jsdom では実ネットワークに出て解決タイミングが不定になり、
//      テスト本体がその解決を待たずに終わると teardown 後に then が flush され、
//      破棄済み環境での setState が "window is not defined" の Unhandled Rejection を生む。
//  (2) test-setup.ts の i18n.changeLanguage('ja') は非同期で、初期化完了前に
//      assert すると t(key) が翻訳済み文字列ではなく key をそのまま返し、
//      "停止中" を含む案内文の照合が散発的に失敗する。
// 対策: fetch を即解決でモックし、各テストで i18n の ja 初期化完了を待ってから、
//       かつ findBy/waitFor で解決後の状態を待ってから assert する。
beforeEach(async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(
      JSON.stringify({ has_admin: true, bootstrap_configured: true }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    ),
  )
  // i18n の ja 初期化が完了してから描画・照合する (生キー照合の flaky を防ぐ)。
  await i18n.changeLanguage('ja')
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('LoginPage password reset link gating (#504)', () => {
  it('無効時はリセットリンクを出さず案内文を表示する', async () => {
    resetFlag.value = false
    render(<LoginPage onLogin={() => {}} />)
    expect(document.querySelector('a[href="#/password/reset"]')).toBeNull()
    // 無効時の案内文 (翻訳済み) が出るまで待つ。ja.json の disabled_message は
    // "現在、パスワードリセットは停止中です。管理者へお問い合わせください。"。
    expect(
      await screen.findByText(/停止中|お問い合わせ|contact/i),
    ).toBeTruthy()
    // mount 時の非同期 bootstrap-status 取得が解決・反映されるまで待ってから終える。
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled())
  })

  it('有効時はリセットリンクを表示する', async () => {
    resetFlag.value = true
    render(<LoginPage onLogin={() => {}} />)
    expect(document.querySelector('a[href="#/password/reset"]')).not.toBeNull()
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled())
  })
})
