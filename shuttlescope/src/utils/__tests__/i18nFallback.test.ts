import { describe, it, expect } from 'vitest'
import { tOr } from '../i18nFallback'
import ja from '@/i18n/ja.json'
import en from '@/i18n/en.json'

describe('tOr', () => {
  it('キーをそのまま返された (未登録) ときは fallback', () => {
    expect(tOr((k) => k, 'a.b', '既定文')).toBe('既定文')
  })
  it('空文字のときも fallback', () => {
    expect(tOr(() => '', 'a.b', '既定文')).toBe('既定文')
  })
  it('訳があればそれを返す', () => {
    expect(tOr(() => '訳', 'a.b', '既定文')).toBe('訳')
  })
})

function get(obj: unknown, path: string): unknown {
  return path.split('.').reduce<unknown>((o, k) => (o as Record<string, unknown> | undefined)?.[k], obj)
}

describe('同意画面・設定で使う i18n キーが ja/en 両方にある', () => {
  const keys = [
    'onboarding.consent.exit_hint',
    'onboarding.consent.back_to_site',
    'onboarding.consent.back_to_login',
    'settings.consent.types.body_disclose_to_analyst',
    'settings.consent.types.body_disclose_to_coach',
    'settings.consent.required_status_on',
    'settings.consent.required_status_off',
    'settings.consent.status_none',
    'auto.SettingsPage.tutorial_status_completed',
    'auto.SettingsPage.tutorial_status_skipped',
  ]
  for (const k of keys) {
    it(k, () => {
      expect(typeof get(ja, k)).toBe('string')
      expect(typeof get(en, k)).toBe('string')
    })
  }
})
