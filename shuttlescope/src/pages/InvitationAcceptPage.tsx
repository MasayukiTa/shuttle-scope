import { useEffect, useState } from 'react'
import { useSearchParams, Link, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { apiGet, apiPost } from '@/api/client'
import { errorMessage } from '@/utils/errors'

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
    } catch (err: unknown) {
      setError(errorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  const fieldCls =
    'w-full border border-[var(--ss-ctrl-border)] rounded-ss-md px-3 py-2.5 text-base min-h-[44px] ' +
    'bg-[var(--ss-ctrl-bg)] text-[var(--ss-ctrl-text)] outline-none transition-colors duration-fast ease-out'

  if (loading) {
    return (
      <div className="min-h-[100svh] flex items-center justify-center bg-[var(--ss-bg-app)]">
        <p className="text-[var(--ss-t2)]">{t('app.loading')}</p>
      </div>
    )
  }
  if (!info) {
    return (
      <div
        className="min-h-[100svh] flex items-center justify-center bg-[var(--ss-bg-app)] p-4"
        style={{ paddingBottom: 'max(1rem, env(safe-area-inset-bottom))' }}
      >
        <div className="max-w-md w-full bg-[var(--ss-surface-1)] border border-[var(--ss-border)] rounded-ss-lg shadow-card p-6 text-center space-y-4">
          <p className="text-[var(--ss-bad)]">{error ?? t('auth.invitation.invalid')}</p>
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
        <h1 className="text-xl font-semibold tracking-[-0.014em] text-[var(--ss-t1)]">{t('auth.invitation.title')}</h1>

        <div className="rounded-ss-md bg-[var(--ss-info-bg)] border border-[var(--ss-info-border)] p-3 text-sm space-y-1 text-[var(--ss-info-text)]">
          <div><span className="font-medium">{t('auth.email')}:</span> {info.email}</div>
          <div><span className="font-medium">{t('auth.invitation.role')}:</span> {info.role}</div>
        </div>

        <div>
          <label className="block text-sm font-medium mb-1 text-[var(--ss-t2)]">{t('auth.register.username')}</label>
          <input type="text" value={username} onChange={(e) => setUsername(e.target.value)}
                 required minLength={3} maxLength={64}
                 autoComplete="username" autoCapitalize="none" autoCorrect="off"
                 className={fieldCls} />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1 text-[var(--ss-t2)]">{t('auth.register.password')}</label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                 required minLength={8} maxLength={128}
                 autoComplete="new-password"
                 className={fieldCls} />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1 text-[var(--ss-t2)]">{t('auth.register.display_name_optional')}</label>
          <input type="text" value={displayName} onChange={(e) => setDisplayName(e.target.value)}
                 maxLength={100}
                 autoComplete="name"
                 className={fieldCls} />
        </div>

        {error && (
          <div className="text-sm rounded-ss-md border px-3 py-2 bg-[var(--ss-danger-bg)] border-[var(--ss-danger-border)] text-[var(--ss-danger-text)]">
            {error}
          </div>
        )}

        <button type="submit" disabled={submitting}
                className="w-full bg-[var(--ss-brand)] hover:bg-[var(--ss-brand-hover)] text-white text-sm font-medium px-4 py-2 rounded-ss-md disabled:opacity-50 transition-colors duration-fast ease-out">
          {submitting ? t('app.loading') : t('auth.invitation.accept')}
        </button>
      </form>
    </div>
  )
}
