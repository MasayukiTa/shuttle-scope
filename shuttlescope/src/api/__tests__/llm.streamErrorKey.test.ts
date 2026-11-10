import { describe, it, expect } from 'vitest'
import { llmStreamErrorKey } from '@/api/llm'
import ja from '@/i18n/ja.json'
import en from '@/i18n/en.json'

function lookup(dict: unknown, key: string): unknown {
  return key.split('.').reduce<unknown>(
    (o, k) => (o && typeof o === 'object' ? (o as Record<string, unknown>)[k] : undefined),
    dict,
  )
}

describe('llmStreamErrorKey', () => {
  const codes = [
    'budget_exceeded',
    'provider_timeout',
    'provider_unavailable',
    'provider_rate_limited',
    'provider_auth',
    'provider_rejected',
    'generation_failed',
  ]

  it('maps every backend error code to a key that exists in both dictionaries', () => {
    for (const code of codes) {
      const key = llmStreamErrorKey(code)
      expect(key, code).not.toBeNull()
      expect(typeof lookup(ja, key as string), `ja ${key}`).toBe('string')
      expect(typeof lookup(en, key as string), `en ${key}`).toBe('string')
    }
  })

  it('does not map free text, so upstream text is never shown as a translation key', () => {
    expect(llmStreamErrorKey('HTTP 500')).toBeNull()
    expect(llmStreamErrorKey('constructor')).toBeNull()
    expect(llmStreamErrorKey('')).toBeNull()
    expect(llmStreamErrorKey(undefined)).toBeNull()
  })
})
