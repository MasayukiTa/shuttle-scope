/**
 * 監査 #532: ウォームアップ観察の入口ボタン名とパネル見出しが一致することを保証する。
 *
 * AnnotatorPage の入口ボタンは t('warmup.button')、開いたパネルの見出しは
 * t('warmup.title') を使う。この2つが食い違うと、利用者は「公開練習メモ」を
 * 押したのに「試合前ウォームアップ観察」が開くことになり、同じ機能と
 * 認識できない。ja / en 両方で一致を強制する。
 */
import { describe, it, expect } from 'vitest'
import ja from '@/i18n/ja.json'
import en from '@/i18n/en.json'

describe('warmup entry label matches panel heading (audit #532)', () => {
  it('ja: warmup.button equals warmup.title', () => {
    expect(ja.warmup.button).toBe(ja.warmup.title)
  })

  it('en: warmup.button equals warmup.title', () => {
    expect(en.warmup.button).toBe(en.warmup.title)
  })

  it('ja: entry label no longer uses the old mismatched wording', () => {
    expect(ja.warmup.button).not.toBe('公開練習メモ')
  })

  it('both locales keep a non-empty label', () => {
    expect(ja.warmup.button.length).toBeGreaterThan(0)
    expect(en.warmup.button.length).toBeGreaterThan(0)
  })
})
