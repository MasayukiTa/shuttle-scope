import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { apiPost } from '@/api/client'
import { TurnstileWidget } from '@/components/auth/TurnstileWidget'
import { errorMessage } from '@/utils/errors'

export default function PasswordResetRequestPage() {
  const { t } = useTranslation()
  const [email, setEmail] = useState('')
  const [tsToken, setTsToken] = useState('')
  const [loading, setLoading] = useState(false)
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // 現状 password reset API は無効化されている (SS_PASSWORD_RESET_ENABLED=0 で 503)
  const RESET_DISABLED = true

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (RESET_DISABLED) {
      setError('現在、パスワードリセットは受付を停止しております。管理者までお問い合わせください。')
      return
    }
    if (loading) return
    setLoading(true)
    setError(null)
    try {
      await apiPost('/auth/password/request_reset', {
        email,
        turnstile_token: tsToken || null,
      })
      setDone(true)
    } catch (err: unknown) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      className="min-h-[100svh] flex items-center justify-center bg-[var(--ss-bg-app)] p-4"
      style={{ paddingBottom: 'max(1rem, env(safe-area-inset-bottom))' }}
    >
      <form onSubmit={handleSubmit}
            className="max-w-md w-full bg-[var(--ss-surface-1)] border border-[var(--ss-border)] rounded-ss-lg shadow-card p-6 space-y-4">
        <h1 className="text-xl font-semibold tracking-[-0.014em] text-[var(--ss-t1)]">{t('auth.password_reset_request.title')}</h1>
        <p className="text-sm text-[var(--ss-t2)]">
          {t('auth.password_reset_request.description')}
        </p>

        <div>
          <label className="block text-sm font-medium mb-1 text-[var(--ss-t2)]">{t('auth.email')}</label>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                 required maxLength={255}
                 disabled={done}
                 inputMode="email" autoComplete="email" autoCapitalize="none" autoCorrect="off"
                 className="w-full border border-[var(--ss-ctrl-border)] rounded-ss-md px-3 py-2.5 text-base min-h-[44px] bg-[var(--ss-ctrl-bg)] text-[var(--ss-ctrl-text)] outline-none disabled:opacity-60 transition-colors duration-fast ease-out" />
        </div>

        {!done && <TurnstileWidget onToken={setTsToken} />}

        {error && (
          <div className="text-sm rounded-ss-md border px-3 py-2 bg-[var(--ss-danger-bg)] border-[var(--ss-danger-border)] text-[var(--ss-danger-text)]">
            {error}
          </div>
        )}

        {done ? (
          <div className="rounded-ss-md border p-3 text-sm bg-[var(--ss-success-bg)] border-[var(--ss-success-border)] text-[var(--ss-success-text)]">
            {t('auth.password_reset_request.sent_message')}
          </div>
        ) : (
          <button type="submit" disabled={loading || RESET_DISABLED}
                  className="w-full bg-[var(--ss-brand)] hover:bg-[var(--ss-brand-hover)] text-white text-sm font-medium px-4 py-2 rounded-ss-md disabled:opacity-50 transition-colors duration-fast ease-out">
            {loading ? t('app.loading') : t('auth.password_reset_request.submit')}
          </button>
        )}

        <Link to="/login" className="block text-center text-sm text-[var(--ss-brand)] hover:text-[var(--ss-brand-hover)] hover:underline">
          {t('auth.back_to_login')}
        </Link>
      </form>
    </div>
  )
}
