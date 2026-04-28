import { useEffect, useState } from 'react'
import { useSearchParams, Link, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { apiGet, apiPost } from '@/api/client'

interface InviteInfo {
  email: string
  role: string
  team_id: number | null
  expires_at: string
}

export default function InvitationAcceptPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const token = params.get('token') ?? ''
  const [info, setInfo] = useState<InviteInfo | null>(null)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!token) {
      setError(t('auth.verify.missing_token'))
      return
    }
    setLoading(true)
    apiGet<{ success: boolean; data: InviteInfo }>(`/auth/invitation/peek?token=${encodeURIComponent(token)}`)
      .then((r) => setInfo(r.data))
      .catch((err) => setError(err?.message ?? String(err)))
      .finally(() => setLoading(false))
  }, [token, t])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (submitting) return
    setSubmitting(true)
    setError(null)
    try {
      await apiPost('/auth/invitation/accept', {
        token,
        username,
        password,
        display_name: displayName || null,
      })
      navigate('/login')
    } catch (err: any) {
      setError(err?.message ?? String(err))
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <p>{t('app.loading')}</p>
      </div>
    )
  }
  if (!info) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900 p-4">
        <div className="max-w-md w-full bg-white dark:bg-gray-800 rounded-lg shadow p-6 text-center space-y-4">
          <p className="text-red-600">{error ?? t('auth.invitation.invalid')}</p>
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
        <h1 className="text-xl font-bold">{t('auth.invitation.title')}</h1>

        <div className="rounded bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 p-3 text-sm space-y-1">
          <div><span className="font-medium">{t('auth.email')}:</span> {info.email}</div>
          <div><span className="font-medium">{t('auth.invitation.role')}:</span> {info.role}</div>
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">{t('auth.register.username')}</label>
          <input type="text" value={username} onChange={(e) => setUsername(e.target.value)}
                 required minLength={3} maxLength={64}
                 className="w-full rounded border px-3 py-2 text-sm dark:bg-gray-700 dark:border-gray-600" />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">{t('auth.register.password')}</label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                 required minLength={8} maxLength={128}
                 className="w-full rounded border px-3 py-2 text-sm dark:bg-gray-700 dark:border-gray-600" />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">{t('auth.register.display_name_optional')}</label>
          <input type="text" value={displayName} onChange={(e) => setDisplayName(e.target.value)}
                 maxLength={100}
                 className="w-full rounded border px-3 py-2 text-sm dark:bg-gray-700 dark:border-gray-600" />
        </div>

        {error && <div className="text-sm text-red-600">{error}</div>}

        <button type="submit" disabled={submitting}
                className="w-full bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-4 py-2 rounded disabled:opacity-50">
          {submitting ? t('app.loading') : t('auth.invitation.accept')}
        </button>
      </form>
    </div>
  )
}
