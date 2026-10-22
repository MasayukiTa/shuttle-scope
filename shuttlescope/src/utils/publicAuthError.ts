import { errorStatus } from '@/utils/errors'

export type PublicAuthScope = 'register' | 'invitation_peek' | 'invitation_accept'

/**
 * 公開 (未認証) 認証画面の失敗を、利用者向け文言の i18n キーへ変換する。
 * backend の detail / response body / Error.message は画面に出さない。
 * 判定は HTTP status と画面の種類だけで行う (本文の文言に依存しない)。
 */
export function publicAuthErrorKey(err: unknown, scope: PublicAuthScope): string {
  const status = errorStatus(err)
  if (status === undefined) return 'auth.public_error.network'
  if (status === 429) return 'auth.public_error.rate_limited'
  if (status === 503) return 'auth.public_error.unavailable'
  if (status >= 500) return 'auth.public_error.server'
  if (status === 409) return 'auth.public_error.conflict'
  if (status === 400) {
    return scope === 'register'
      ? 'auth.public_error.invalid_input'
      : 'auth.public_error.invitation_invalid'
  }
  if (status === 422) return 'auth.public_error.invalid_input'
  return 'auth.public_error.unknown'
}
