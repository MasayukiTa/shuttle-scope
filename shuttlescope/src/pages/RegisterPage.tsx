import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { apiPost } from '@/api/client'
import { TurnstileWidget } from '@/components/auth/TurnstileWidget'

export default function RegisterPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [tsToken, setTsToken] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (loading) return
    setLoading(true)
    setError(null)
    try {
      await apiPost('/auth/register', {
        username,
        email,
        password,
        display_name: displayName || null,
        turnstile_token: tsToken || null,
      })
      setSuccess(true)
    } catch (err: any) {
      setError(err?.message ?? String(err))
    } finally {
      setLoading(false)
    }
  }

  if (success) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900 p-4">
        <div className="max-w-md w-full bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-4">
          <h1 className="text-xl font-bold">{t('auth.register.success_title')}</h1>
          <p className="text-sm text-gray-600 dark:text-gray-300">
            {t('auth.register.success_body')}
          </p>
          <Link to="/login" className="block text-blue-600 hover:underline text-sm">
            {t('auth.register.back_to_login')}
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900 p-4">
      <form onSubmit={handleSubmit}
            className="max-w-md w-full bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-4">
        <h1 className="text-xl font-bold">{t('auth.register.title')}</h1>

        {/* 一時的な利用不可バナー (M-B / M-C 完了まで) */}
        <div className="rounded-md border border-amber-300 bg-amber-50 dark:border-amber-700 dark:bg-amber-900/20 p-4 space-y-2">
          <p className="text-sm font-semibold text-amber-900 dark:text-amber-200">
            {t('auth.register.unavailable_banner_title')}
          </p>
          <p className="text-xs text-amber-800 dark:text-amber-300 leading-relaxed">
            {t('auth.register.unavailable_banner_body')}
          </p>
          <a href="https://shuttle-scope.com/contact"
             target="_blank" rel="noopener noreferrer"
             className="inline-block text-xs text-amber-900 dark:text-amber-200 underline hover:no-underline">
            {t('auth.register.unavailable_banner_contact')} →
          </a>
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">
            {t('auth.register.username')}
          </label>
          <input type="text" value={username} onChange={(e) => setUsername(e.target.value)}
                 required minLength={3} maxLength={64}
                 className="w-full rounded border px-3 py-2 text-sm dark:bg-gray-700 dark:border-gray-600" />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">
            {t('auth.register.email')}
          </label>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                 required maxLength={255}
                 className="w-full rounded border px-3 py-2 text-sm dark:bg-gray-700 dark:border-gray-600" />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">
            {t('auth.register.password')}
          </label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                 required minLength={8} maxLength={128}
                 className="w-full rounded border px-3 py-2 text-sm dark:bg-gray-700 dark:border-gray-600" />
          <p className="mt-1 text-xs text-gray-500">{t('auth.register.password_hint')}</p>
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">
            {t('auth.register.display_name_optional')}
          </label>
          <input type="text" value={displayName} onChange={(e) => setDisplayName(e.target.value)}
                 maxLength={100}
                 className="w-full rounded border px-3 py-2 text-sm dark:bg-gray-700 dark:border-gray-600" />
        </div>

        <TurnstileWidget onToken={setTsToken} />

        {error && <div className="text-sm text-red-600">{error}</div>}

        <button type="submit" disabled={loading}
                className="w-full bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-4 py-2 rounded disabled:opacity-50">
          {loading ? t('app.loading') : t('auth.register.submit')}
        </button>

        <Link to="/login" className="block text-center text-sm text-blue-600 hover:underline">
          {t('auth.register.have_account')}
        </Link>
      </form>
    </div>
  )
}
