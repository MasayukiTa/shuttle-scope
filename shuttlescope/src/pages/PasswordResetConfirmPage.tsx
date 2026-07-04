import { useState } from 'react'
import { useSearchParams, Link, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { apiPost } from '@/api/client'
import { errorMessage } from '@/utils/errors'

export default function PasswordResetConfirmPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const token = params.get('token') ?? ''
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  const fieldCls =
    'w-full border border-[var(--ss-ctrl-border)] rounded-ss-md px-3 py-2.5 text-base min-h-[44px] ' +
    'bg-[var(--ss-ctrl-bg)] text-[var(--ss-ctrl-text)] outline-none transition-colors duration-fast ease-out'

  if (!token) {
    return (
      <div
        className="min-h-[100svh] flex items-center justify-center bg-[var(--ss-bg-app)] p-4"
        style={{ paddingBottom: 'max(1rem, env(safe-area-inset-bottom))' }}
      >
        <div className="max-w-md w-full bg-[var(--ss-surface-1)] border border-[var(--ss-border)] rounded-ss-lg shadow-card p-6 text-center">
          <p className="text-[var(--ss-bad)]">{t('auth.verify.missing_token')}</p>
          <Link to="/login" className="block mt-4 text-[var(--ss-brand)] hover:text-[var(--ss-brand-hover)] hover:underline text-sm">
            {t('auth.back_to_login')}
          </Link>
        </div>
      </div>
    )
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (loading) return
    if (password !== confirm) {
      setError(t('auth.password_reset_confirm.mismatch'))
      return
    }
    setLoading(true)
    setError(null)
    try {
      await apiPost('/auth/password/reset', { token, new_password: password })
      setDone(true)
      setTimeout(() => navigate('/login'), 2500)
    } catch (err: unknown) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  if (done) {
    return (
      <div
        className="min-h-[100svh] flex items-center justify-center bg-[var(--ss-bg-app)] p-4"
        style={{ paddingBottom: 'max(1rem, env(safe-area-inset-bottom))' }}
      >
        <div className="max-w-md w-full bg-[var(--ss-surface-1)] border border-[var(--ss-border)] rounded-ss-lg shadow-card p-6 text-center space-y-4">
          <p className="text-[var(--ss-success)]">
            {t('auto.PasswordResetConfirmPage.check_mark')} {t('auth.password_reset_confirm.done')}
          </p>
          <Link to="/login" className="block text-[var(--ss-brand)] hover:text-[var(--ss-brand-hover)] hover:underline text-sm">
            {t('auth.back_to_login')}
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div
      className="min-h-[100svh] flex items-center justify-center bg-[var(--ss-bg-app)] p-4"
      style={{ paddingBottom: 'max(1rem, env(safe-area-inset-bottom))' }}
    >
      <form onSubmit={handleSubmit}
            className="max-w-md w-full bg-[var(--ss-surface-1)] border border-[var(--ss-border)] rounded-ss-lg shadow-card p-6 space-y-4">
        <h1 className="text-xl font-semibold tracking-[-0.014em] text-[var(--ss-t1)]">{t('auth.password_reset_confirm.title')}</h1>

        <div>
          <label className="block text-sm font-medium mb-1 text-[var(--ss-t2)]">
            {t('auth.password_reset_confirm.new_password')}
          </label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                 required minLength={8} maxLength={128}
                 autoComplete="new-password"
                 className={fieldCls} />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1 text-[var(--ss-t2)]">
            {t('auth.password_reset_confirm.confirm_password')}
          </label>
          <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)}
                 required minLength={8} maxLength={128}
                 autoComplete="new-password"
                 className={fieldCls} />
        </div>

        {error && (
          <div className="text-sm rounded-ss-md border px-3 py-2 bg-[var(--ss-danger-bg)] border-[var(--ss-danger-border)] text-[var(--ss-danger-text)]">
            {error}
          </div>
        )}

        <button type="submit" disabled={loading}
                className="w-full bg-[var(--ss-brand)] hover:bg-[var(--ss-brand-hover)] text-white text-sm font-medium px-4 py-2 rounded-ss-md disabled:opacity-50 transition-colors duration-fast ease-out">
          {loading ? t('app.loading') : t('auth.password_reset_confirm.submit')}
        </button>
      </form>
    </div>
  )
}
