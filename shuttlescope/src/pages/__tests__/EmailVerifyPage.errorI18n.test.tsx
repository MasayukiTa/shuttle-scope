/**
 * #410 (メール確認エラーの生 err.message 露出): verify 失敗時に
 * API/client 例外文字列をそのまま出さず、利用者向けの固定文言 (t キー) へ
 * マッピングし、詳細は console へ退避することを固定する。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { resolve } from 'path'
import ja from '@/i18n/ja.json'
import en from '@/i18n/en.json'

type Dict = Record<string, unknown>
const verify = (d: unknown): Dict =>
  (d as { auth: { verify: Dict } }).auth.verify

describe('#410: メール確認失敗時の利用者向け文言', () => {
  it('auth.verify.failed_invalid が ja/en 両方に文字列で存在する', () => {
    expect(typeof verify(ja).failed_invalid, 'ja.auth.verify.failed_invalid').toBe('string')
    expect(typeof verify(en).failed_invalid, 'en.auth.verify.failed_invalid').toBe('string')
  })

  it('EmailVerifyPage が生例外文字列を画面へ出さない (回帰)', () => {
    const s = readFileSync(resolve(__dirname, '..', 'EmailVerifyPage.tsx'), 'utf-8')
    expect(s).not.toContain('err?.message ?? String(err)')
    expect(s).toContain("t('auth.verify.failed_invalid')")
  })
})
