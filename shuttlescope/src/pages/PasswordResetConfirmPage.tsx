import { useState } from 'react'
import { useSearchParams, Link, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { apiPost } from '@/api/client'

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

  if (!token) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900 p-4">
        <div className="max-w-md w-full bg-white dark:bg-gray-800 rounded-lg shadow p-6 text-center">
          <p className="text-red-600">{t('auth.verify.missing_token')}</p>
          <Link to="/login" className="block mt-4 text-blue-600 hover:underline text-sm">
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
    } catch (err: any) {
      setError(err?.message ?? String(err))
    } finally {
      setLoading(false)
    }
  }

  if (done) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900 p-4">
        <div className="max-w-md w-full bg-white dark:bg-gray-800 rounded-lg shadow p-6 text-center space-y-4">
          <p className="text-green-700 dark:text-green-400">
            ✅ {t('auth.password_reset_confirm.done')}
          </p>
          <Link to="/login" className="block text-blue-600 hover:underline text-sm">
            {t('auth.back_to_login')}
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900 p-4">
      <form onSubmit={handleSubmit}
            className="max-w-md w-full bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-4">
        <h1 className="text-xl font-bold">{t('auth.password_reset_confirm.title')}</h1>

        <div>
          <label className="block text-sm font-medium mb-1">
            {t('auth.password_reset_confirm.new_password')}
          </label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                 required minLength={8} maxLength={128}
                 className="w-full rounded border px-3 py-2 text-sm dark:bg-gray-700 dark:border-gray-600" />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">
            {t('auth.password_reset_confirm.confirm_password')}
          </label>
          <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)}
                 required minLength={8} maxLength={128}
                 className="w-full rounded border px-3 py-2 text-sm dark:bg-gray-700 dark:border-gray-600" />
        </div>

        {error && <div className="text-sm text-red-600">{error}</div>}

        <button type="submit" disabled={loading}
                className="w-full bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-4 py-2 rounded disabled:opacity-50">
          {loading ? t('app.loading') : t('auth.password_reset_confirm.submit')}
        </button>
      </form>
    </div>
  )
}
