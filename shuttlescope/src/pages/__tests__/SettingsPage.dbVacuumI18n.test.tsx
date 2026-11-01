/**
 * #14 (データ管理にDB実装詳細が露出): auto_vacuum トグルボタンの
 * title 文言 (k24/k25) から SQLite 内部用語 (INCREMENTAL / VACUUM / OFF) を除き、
 * 利用者向けの表現へ言い換えたことを固定する。
 */
import { describe, it, expect } from 'vitest'
import ja from '@/i18n/ja.json'
import en from '@/i18n/en.json'

type Dict = Record<string, unknown>
const sp = (d: unknown): Dict =>
  (d as { auto: { SettingsPage: Dict } }).auto.SettingsPage

describe('#14: DB 最適化ボタン文言から内部 SQL 用語を除く', () => {
  it('k24/k25 が ja/en 両方に文字列で存在する', () => {
    for (const d of [ja, en]) {
      expect(typeof sp(d).k24).toBe('string')
      expect(typeof sp(d).k25).toBe('string')
    }
  })

  it('k24/k25 に SQLite 内部用語が残っていない (回帰)', () => {
    for (const d of [ja, en]) {
      const k24 = String(sp(d).k24)
      const k25 = String(sp(d).k25)
      expect(k24).not.toContain('INCREMENTAL')
      expect(k24).not.toContain('VACUUM')
      expect(k25).not.toContain('OFF')
    }
  })
})
