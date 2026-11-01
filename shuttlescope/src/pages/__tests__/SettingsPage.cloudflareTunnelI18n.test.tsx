/**
 * #13 (共有設定の開発内部情報露出): Cloudflare named tunnel の状態文言を
 * TSX にハードコードせず t() キー経由で表示し、repo 外パス等の
 * 内部実装情報を利用者向け UI に出さないことを固定する。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { resolve } from 'path'
import ja from '@/i18n/ja.json'
import en from '@/i18n/en.json'

type Dict = Record<string, unknown>
const settingsPage = (d: unknown): Dict =>
  (d as { auto: { SettingsPage: Dict } }).auto.SettingsPage

const KEYS = ['cloudflare_named_tunnel_ready', 'cloudflare_named_tunnel_not_ready']

describe('#13: Cloudflare named tunnel の状態文言', () => {
  it('t() キーが ja/en 両方に文字列で存在する', () => {
    for (const k of KEYS) {
      expect(typeof settingsPage(ja)[k], `ja.auto.SettingsPage.${k}`).toBe('string')
      expect(typeof settingsPage(en)[k], `en.auto.SettingsPage.${k}`).toBe('string')
    }
  })

  it('SettingsPage に repo 外パス等の内部情報が残っていない (回帰)', () => {
    const s = readFileSync(resolve(__dirname, '..', 'SettingsPage.tsx'), 'utf-8')
    expect(s).not.toContain('cloudflare-shuttle-scope')
    expect(s).not.toContain('.cloudflared')
    expect(s).not.toContain('repo外')
  })
})
