/**
 * 同意画面: 任意同意は明示 opt-in (初期未チェック)、生キー非表示、「後で」の記憶。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

const submitConsents = vi.fn().mockResolvedValue({})
vi.mock('@/api/client', () => ({
  getMyConsents: vi.fn().mockResolvedValue({
    data: {
      consent_required: false,
      current_versions: { privacy_policy: '1.3', terms: '1.3', data_contribution: '1.0' },
      required_types: ['service_delivery', 'beta_agreement'],
      optional_types: [],
      consents: [],
      viewer_is_minor: false,
    },
  }),
  submitConsents: (...a: unknown[]) => submitConsents(...a),
}))
vi.mock('@/hooks/useAuth', () => ({ useAuth: () => ({ role: 'player', userId: 7 }) }))

import OnboardingConsentPage from '../OnboardingConsentPage'
import { isOptionalConsentDeferred } from '@/utils/consentDeferral'

const OPTIONAL_LABELS = [
  'AI モデル学習への利用に同意します',
  '学術研究への利用に同意します',
  '体組成データをアナリストに開示します',
  '体組成データをコーチに開示します',
]

describe('OnboardingConsentPage', () => {
  beforeEach(() => {
    window.localStorage.clear()
    submitConsents.mockClear()
  })

  it('任意同意 4 件はすべて初期未チェック', async () => {
    render(<OnboardingConsentPage optionalOnly onCompleted={() => {}} onDeferred={() => {}} />)
    for (const label of OPTIONAL_LABELS) {
      const box = (await screen.findByText(label)).closest('label')!.querySelector('input')!
      expect(box.checked).toBe(false)
    }
  })

  it('何もチェックせず保存すると全件 consent_given=false で送る', async () => {
    const done = vi.fn()
    render(<OnboardingConsentPage optionalOnly onCompleted={done} onDeferred={() => {}} />)
    fireEvent.click(await screen.findByText('回答して保存'))
    await waitFor(() => expect(done).toHaveBeenCalled())
    const sent = submitConsents.mock.calls[0][0].consents as { consent_type: string; consent_given: boolean }[]
    expect(sent).toHaveLength(4)
    expect(sent.every((c) => c.consent_given === false)).toBe(true)
  })

  it('生の i18n キーを画面に出さない', async () => {
    const { container } = render(<OnboardingConsentPage optionalOnly onCompleted={() => {}} />)
    await screen.findByText('回答して保存')
    expect(container.textContent).not.toMatch(/onboarding\.consent\./)
  })

  it('「後で回答する」で未提出のまま一定期間の再表示抑止を記憶する', async () => {
    const deferred = vi.fn()
    render(<OnboardingConsentPage optionalOnly onCompleted={() => {}} onDeferred={deferred} />)
    fireEvent.click(await screen.findByText('任意項目は後で回答する'))
    expect(deferred).toHaveBeenCalled()
    expect(submitConsents).not.toHaveBeenCalled()
    expect(isOptionalConsentDeferred(7)).toBe(true)
  })
})
