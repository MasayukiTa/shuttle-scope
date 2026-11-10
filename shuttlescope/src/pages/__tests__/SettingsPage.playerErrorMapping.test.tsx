/**
 * 設定の選手 create / update / delete / 確認済み変更のエラー表示 (項目585 の設定領域)
 *
 * 製品ルール: 利用者向けエラーは HTTP status・backend detail・JS 例外文字列を
 * そのまま出さず、安定した利用者向け文言 (common_ui.error_* / player_*) へ変換する。
 * 詳細は console へ退避する。ここでは (1) 変換に使う i18n キーが ja/en 両方にあること、
 * (2) 旧来の生エラー alert 文字列が SettingsPage に残っていないこと (回帰) を固定する。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { resolve } from 'path'
import ja from '@/i18n/ja.json'
import en from '@/i18n/en.json'

type Dict = Record<string, unknown>
const commonUi = (d: unknown): Dict => (d as { common_ui: Dict }).common_ui
const settingsUi = (d: unknown): Dict => (d as { settings: { ui: Dict } }).settings.ui

const COMMON_KEYS = [
  'error_session_expired',
  'error_forbidden',
  'error_conflict',
  'error_invalid_input',
  'player_save_failed',
  'player_delete_failed',
  'player_verify_failed',
  'player_in_use',
]

describe('項目585: 選手操作エラーの利用者向け文言', () => {
  it('変換に使う common_ui キーが ja/en 両方に文字列で存在する', () => {
    for (const k of COMMON_KEYS) {
      expect(typeof commonUi(ja)[k], `ja.common_ui.${k}`).toBe('string')
      expect(typeof commonUi(en)[k], `en.common_ui.${k}`).toBe('string')
    }
  })

  it('settings.ui.player_delete_open_matches が ja/en 両方に存在する', () => {
    expect(typeof settingsUi(ja).player_delete_open_matches).toBe('string')
    expect(typeof settingsUi(en).player_delete_open_matches).toBe('string')
  })

  it('SettingsPage が旧来の生エラー alert を出していない (回帰)', () => {
    const s = readFileSync(resolve(__dirname, '..', 'SettingsPage.tsx'), 'utf-8')
    expect(s).not.toContain('保存に失敗しました (HTTP')
    expect(s).not.toContain('確認済み設定に失敗しました:')
    expect(s).not.toContain('削除できません:')
  })

  it('選手 onError が userFacingPlayerError を使う', () => {
    const s = readFileSync(resolve(__dirname, '..', 'SettingsPage.tsx'), 'utf-8')
    expect(s).toContain('const userFacingPlayerError =')
    const uses = s.split('userFacingPlayerError(').length - 1
    expect(uses).toBeGreaterThanOrEqual(4)
  })
})
