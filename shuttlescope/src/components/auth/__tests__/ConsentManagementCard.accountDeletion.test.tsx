/**
 * #530: 必須同意は「撤回にはアカウント削除が必要」とだけ案内し、どこで削除/退会を
 * 申請するのかの導線が無かった。自己削除機能は未提供のため、その場に申請先 (contact)
 * を mailto リンクで示すことを固定する。consent / privacy の法的文言は変更しない。
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k, i18n: { language: 'ja' } }),
}))
vi.mock('@/components/common/MIcon', () => ({ MIcon: () => null }))

const requiredType = 'service_delivery'
const optionalType = 'ai_training'

vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
  useMutation: () => ({ mutate: vi.fn(), isError: false }),
  useQuery: () => ({
    isLoading: false,
    error: null,
    data: {
      data: {
        required_types: [requiredType],
        optional_types: [optionalType],
        consents: [
          { consent_type: requiredType, consent_given: true, given_at: '2026-01-01T00:00:00Z', withdrawn_at: null },
          { consent_type: optionalType, consent_given: true, given_at: '2026-01-01T00:00:00Z', withdrawn_at: null },
        ],
        current_versions: { privacy_policy: '1', terms: '1' },
      },
    },
    refetch: vi.fn(),
  }),
}))

vi.mock('@/api/client', () => ({
  getMyConsents: vi.fn(),
  withdrawConsent: vi.fn(),
  submitConsents: vi.fn(),
}))

import { ConsentManagementCard } from '../ConsentManagementCard'

describe('ConsentManagementCard account-deletion contact (#530)', () => {
  it('shows an account-deletion contact link for the required (non-withdrawable) consent', () => {
    render(<ConsentManagementCard isLight />)

    // 必須同意は従来どおり「撤回不可」と表示される
    expect(screen.getByText('settings.consent.required_note')).toBeInTheDocument()

    // 追加: アカウント削除の申請先を案内する mailto リンクが存在する
    const link = screen.getByText('settings.consent.account_deletion_contact')
    expect(link).toBeInTheDocument()
    expect(link.closest('a')).toHaveAttribute('href', 'mailto:contact@shuttle-scope.com')
  })
})
