import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { apiPost } from '@/api/client'
import { TurnstileWidget } from '@/components/auth/TurnstileWidget'

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
    } catch (err: any) {
      setError(err?.message ?? String(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900 p-4">
      <form onSubmit={handleSubmit}
            className="max-w-md w-full bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-4">
        <h1 className="text-xl font-bold">{t('auth.password_reset_request.title')}</h1>
        <p className="text-sm text-gray-600 dark:text-gray-300">
          {t('auth.password_reset_request.description')}
        </p>

        <div>
          <label className="block text-sm font-medium mb-1">{t('auth.email')}</label>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                 required maxLength={255}
                 disabled={done}
                 className="w-full rounded border px-3 py-2 text-sm dark:bg-gray-700 dark:border-gray-600" />
        </div>

        {!done && <TurnstileWidget onToken={setTsToken} />}

        {error && <div className="text-sm text-red-600">{error}</div>}

        {done ? (
          <div className="rounded bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 p-3 text-sm text-green-800 dark:text-green-300">
            {t('auth.password_reset_request.sent_message')}
          </div>
        ) : (
          <button type="submit" disabled={loading || RESET_DISABLED}
                  className="w-full bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-4 py-2 rounded disabled:opacity-50">
            {loading ? t('app.loading') : t('auth.password_reset_request.submit')}
          </button>
        )}

        <Link to="/login" className="block text-center text-sm text-blue-600 hover:underline">
          {t('auth.back_to_login')}
        </Link>
      </form>
    </div>
  )
}
