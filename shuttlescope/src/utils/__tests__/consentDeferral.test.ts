import { describe, it, expect, beforeEach } from 'vitest'
import {
  clearOptionalConsentDeferral,
  deferOptionalConsent,
  isOptionalConsentDeferred,
  OPTIONAL_CONSENT_DEFER_DAYS,
} from '../consentDeferral'

const DAY = 86_400_000

describe('consentDeferral', () => {
  beforeEach(() => window.localStorage.clear())

  it('未設定なら延期されていない', () => {
    expect(isOptionalConsentDeferred(1)).toBe(false)
  })

  it('延期すると期限内は true、期限後は false', () => {
    const t0 = 1_000_000_000_000
    deferOptionalConsent(1, t0)
    expect(isOptionalConsentDeferred(1, t0 + (OPTIONAL_CONSENT_DEFER_DAYS - 1) * DAY)).toBe(true)
    expect(isOptionalConsentDeferred(1, t0 + OPTIONAL_CONSENT_DEFER_DAYS * DAY + 1)).toBe(false)
  })

  it('ユーザごとに独立している', () => {
    deferOptionalConsent(1)
    expect(isOptionalConsentDeferred(1)).toBe(true)
    expect(isOptionalConsentDeferred(2)).toBe(false)
  })

  it('clear で消える', () => {
    deferOptionalConsent(1)
    clearOptionalConsentDeferral(1)
    expect(isOptionalConsentDeferred(1)).toBe(false)
  })

  it('壊れた値は延期なし扱い', () => {
    window.localStorage.setItem('shuttlescope_optional_consent_deferred_until:1', 'abc')
    expect(isOptionalConsentDeferred(1)).toBe(false)
  })
})
