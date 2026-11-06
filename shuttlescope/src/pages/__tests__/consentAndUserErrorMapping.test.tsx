/**
 * 同意更新・ユーザ管理の生エラー露出廃止 (項目585 の残り2領域)
 *
 * 製品ルール: 利用者向けエラーは HTTP status・backend detail・JS 例外文字列を
 * そのまま出さず、安定した利用者向け文言へ変換する。詳細は console へ退避する。
 * 同意操作では「変更は保存されていない / 現在の共有状態は維持」を明示する。
 * ここでは (1) 変換に使う i18n キーが ja/en 両方にあること、
 * (2) 旧来の生エラー露出コードが各ソースに残っていないこと (回帰) を固定する。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { resolve } from 'path'
import ja from '@/i18n/ja.json'
import en from '@/i18n/en.json'

type Dict = Record<string, unknown>
const condition = (d: unknown): Dict => (d as { condition: Dict }).condition
const usersManage = (d: unknown): Dict => (d as { users: { manage: Dict } }).users.manage

function src(rel: string): string {
  return readFileSync(resolve(__dirname, '..', rel), 'utf-8')
}

describe('項目585: 同意更新の利用者向け文言', () => {
  it('condition.consent_update_failed_v2 が ja/en 両方に文字列で存在する', () => {
    expect(typeof condition(ja).consent_update_failed_v2).toBe('string')
    expect(typeof condition(en).consent_update_failed_v2).toBe('string')
  })

  it('同意文言が「保存されていない / 維持」を明示する (日本語)', () => {
    const s = condition(ja).consent_update_failed_v2 as string
    expect(s).toContain('保存')
    expect(s).toContain('維持')
  })

  it('ConditionPage が生の例外文字列を alert していない (回帰)', () => {
    const s = src('ConditionPage.tsx')
    expect(s).not.toContain('String(e).slice(0, 200)')
    expect(s).toContain('consent_update_failed_v2')
  })
})

describe('項目585: ユーザ管理の利用者向け文言', () => {
  it('reset_password_failed / reset_limits_failed が ja/en 両方に存在する', () => {
    for (const d of [ja, en]) {
      expect(typeof usersManage(d).reset_password_failed).toBe('string')
      expect(typeof usersManage(d).reset_limits_failed).toBe('string')
    }
  })

  it('UserManagementPage が生の err.message を alert していない (回帰)', () => {
    const s = src('UserManagementPage.tsx')
    expect(s).not.toContain("message || 'error'")
    expect(s).not.toContain("message || 'reset error'")
    expect(s).toContain('userFacingUserError')
    // password reset と limit reset の 2 箇所で使う
    // 定義行は `userFacingUserError = (` で括弧前に空白があるためここでは数えない。
    // password reset と limit reset の呼び出し 2 箇所を固定する。
    const uses = s.split('userFacingUserError(').length - 1
    expect(uses).toBeGreaterThanOrEqual(2)
  })
})
