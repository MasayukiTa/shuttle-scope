/**
 * 任意同意の prefill は owner 方針 (2026-10-31) に従う。
 *
 * 文書が改定されたとき再同意を求めるのは、改定された文書に紐づく同意だけ。
 * ただし任意同意の所属文書は一意に定まらず、同意レコードが保持するのは
 * privacy_policy_version と terms_version の 2 つだけなので、保守側に倒す:
 * 「記録に付随する privacy / terms の両方が現行版と一致する record だけ」
 * 過去の回答を prefill し、いずれかが改定されていれば未チェックに戻す。
 * version 欠落も一致を確認できないので未チェック扱い。
 * 現行版で意図的に外した record (consent_given=false) はそのまま尊重する。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

const getMyConsents = vi.fn()
vi.mock('@/api/client', () => ({
  getMyConsents: (...a: unknown[]) => getMyConsents(...a),
  submitConsents: vi.fn().mockResolvedValue({}),
}))
vi.mock('@/hooks/useAuth', () => ({ useAuth: () => ({ role: 'player', userId: 7 }) }))

import OnboardingConsentPage from '../OnboardingConsentPage'

// 任意同意ラベル -> checkbox の checked 状態を読む
async function checkedOf(label: string): Promise<boolean> {
  const box = (await screen.findByText(label)).closest('label')!.querySelector('input')!
  return box.checked
}

const AI_LABEL = 'AI モデル学習への利用に同意します'

function stateWith(consents: unknown[], versions = { privacy_policy: '1.3', terms: '1.3', data_contribution: '1.0' }) {
  return {
    data: {
      consent_required: false,
      current_versions: versions,
      required_types: ['service_delivery', 'beta_agreement'],
      optional_types: ['ai_training', 'research_participation', 'body_disclose_to_analyst', 'body_disclose_to_coach'],
      consents,
      viewer_is_minor: false,
    },
  }
}

function rec(overrides: Record<string, unknown>) {
  return {
    consent_type: 'ai_training',
    consent_given: true,
    privacy_policy_version: '1.3',
    terms_version: '1.3',
    given_at: '2026-10-01T00:00:00Z',
    withdrawn_at: null,
    ...overrides,
  }
}

describe('OnboardingConsentPage の任意同意 prefill (owner 方針)', () => {
  beforeEach(() => {
    window.localStorage.clear()
    getMyConsents.mockReset()
  })

  it('どの文書も改定されていなければ過去の同意 (true) を prefill する', async () => {
    getMyConsents.mockResolvedValue(stateWith([rec({ consent_given: true })]))
    render(<OnboardingConsentPage optionalOnly onCompleted={() => {}} onDeferred={() => {}} />)
    expect(await checkedOf(AI_LABEL)).toBe(true)
  })

  it('terms だけ改定された record は未チェックに戻す (再回答)', async () => {
    // 旧 terms 1.2 で与えた同意。現行 terms は 1.3。privacy は不変。
    getMyConsents.mockResolvedValue(stateWith([rec({ terms_version: '1.2', consent_given: true })]))
    render(<OnboardingConsentPage optionalOnly onCompleted={() => {}} onDeferred={() => {}} />)
    expect(await checkedOf(AI_LABEL)).toBe(false)
  })

  it('privacy だけ改定された record は未チェックに戻す (再回答)', async () => {
    // 旧 privacy 1.2 で与えた同意。現行 privacy は 1.3。terms は不変。
    getMyConsents.mockResolvedValue(stateWith([rec({ privacy_policy_version: '1.2', consent_given: true })]))
    render(<OnboardingConsentPage optionalOnly onCompleted={() => {}} onDeferred={() => {}} />)
    expect(await checkedOf(AI_LABEL)).toBe(false)
  })

  it('version が欠落した record は一致を確認できないので未チェック扱い', async () => {
    getMyConsents.mockResolvedValue(
      stateWith([rec({ privacy_policy_version: '', terms_version: '', consent_given: true })]),
    )
    render(<OnboardingConsentPage optionalOnly onCompleted={() => {}} onDeferred={() => {}} />)
    expect(await checkedOf(AI_LABEL)).toBe(false)
  })

  it('現行版で意図的に外した撤回 (consent_given=false) はそのまま false を保持する', async () => {
    getMyConsents.mockResolvedValue(
      stateWith([rec({ consent_given: false, withdrawn_at: '2026-10-02T00:00:00Z' })]),
    )
    render(<OnboardingConsentPage optionalOnly onCompleted={() => {}} onDeferred={() => {}} />)
    expect(await checkedOf(AI_LABEL)).toBe(false)
  })
})
