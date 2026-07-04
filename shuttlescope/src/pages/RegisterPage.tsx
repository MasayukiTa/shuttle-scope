import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import i18n from '@/i18n'
import { apiPost } from '@/api/client'
import { TurnstileWidget } from '@/components/auth/TurnstileWidget'
import { errorMessage } from '@/utils/errors'
import { publicSiteUrl } from '@/utils/publicUrl'

export default function RegisterPage() {
  const { t } = useTranslation()
  const _navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [dob, setDob] = useState('')  // yyyy-mm-dd
  const [tsToken, setTsToken] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  // 2026-05-26: 自動確認メールが整うまでの間は admin 手動承認 + 手動メール案内で運用。
  // backend は webhook で admin に通知 → admin が contact_email へ手動でメール送信。
  // mail backend が本実装に切り替わったら verify-mail フローを復活させる。

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
        date_of_birth: dob || null,
      })
      setSuccess(true)
    } catch (err: unknown) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  const fieldCls =
    'w-full border border-[var(--ss-ctrl-border)] rounded-ss-md px-3 py-2.5 text-base min-h-[44px] ' +
    'bg-[var(--ss-ctrl-bg)] text-[var(--ss-ctrl-text)] outline-none transition-colors duration-fast ease-out'
  const labelCls = 'block text-sm font-medium mb-1 text-[var(--ss-t2)]'

  if (success) {
    return (
      <div
        className="min-h-[100svh] flex items-center justify-center bg-[var(--ss-bg-app)] p-4"
        style={{ paddingBottom: 'max(1rem, env(safe-area-inset-bottom))' }}
      >
        <div className="max-w-md w-full bg-[var(--ss-surface-1)] border border-[var(--ss-border)] rounded-ss-lg shadow-card p-6 space-y-4">
          <h1 className="text-xl font-semibold tracking-[-0.014em] text-[var(--ss-t1)]">{t('auth.register.success_title')}</h1>
          <p className="text-sm text-[var(--ss-t2)]">
            {t('auth.register.success_body')}
          </p>
          <Link to="/login" className="block text-[var(--ss-brand)] hover:text-[var(--ss-brand-hover)] hover:underline text-sm">
            {t('auth.register.back_to_login')}
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
        <h1 className="text-xl font-semibold tracking-[-0.014em] text-[var(--ss-t1)]">{t('auth.register.title')}</h1>

        {/* 2026-05-26: 受付中 + 手動承認運用バナー (mail backend 整備までの暫定 UI)。
            色は amber → blue 寄り (案内ニュアンス、停止ではない) */}
        <div className="rounded-ss-md border border-[var(--ss-info-border)] bg-[var(--ss-info-bg)] p-4 space-y-2">
          <p className="text-sm font-semibold text-[var(--ss-info-text)]">
            {t('auth.register.unavailable_banner_title')}
          </p>
          <p className="text-xs text-[var(--ss-info-text)] leading-relaxed">
            {t('auth.register.unavailable_banner_body')}
          </p>
          <a href={publicSiteUrl('/contact', i18n.language)}
             target="_blank" rel="noopener noreferrer"
             className="inline-block text-xs text-[var(--ss-info-text)] underline hover:no-underline">
            {t('auth.register.unavailable_banner_contact')} →
          </a>
        </div>

        <div>
          <label className={labelCls}>
            {t('auth.register.username')}
          </label>
          <input type="text" value={username} onChange={(e) => setUsername(e.target.value)}
                 required minLength={3} maxLength={64}
                 autoComplete="username" autoCapitalize="none" autoCorrect="off"
                 className={fieldCls} />
        </div>

        <div>
          <label className={labelCls}>
            {t('auth.register.email')}
          </label>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                 required maxLength={255}
                 inputMode="email" autoComplete="email" autoCapitalize="none" autoCorrect="off"
                 className={fieldCls} />
        </div>

        <div>
          <label className={labelCls}>
            {t('auth.register.password')}
          </label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                 required minLength={8} maxLength={128}
                 autoComplete="new-password"
                 className={fieldCls} />
          <p className="mt-1 text-xs text-[var(--ss-t3)]">{t('auth.register.password_hint')}</p>
        </div>

        <div>
          <label className={labelCls}>
            {t('auth.register.display_name_optional')}
          </label>
          <input type="text" value={displayName} onChange={(e) => setDisplayName(e.target.value)}
                 maxLength={100}
                 autoComplete="name"
                 className={fieldCls} />
        </div>

        <div>
          <label className={labelCls}>
            {t('auth.register.dob_optional') || '生年月日（任意）'}
          </label>
          <input type="date" value={dob} onChange={(e) => setDob(e.target.value)}
                 max={new Date().toISOString().slice(0, 10)}
                 autoComplete="bday"
                 className={fieldCls} />
          <p className="mt-1 text-xs text-[var(--ss-t3)]">
            {t('auth.register.dob_hint') ||
              '任意入力。AI 学習・研究利用への同意 UI で未成年配慮（PRIVACY §IX-ter）を適用するために使用します。'}
          </p>
        </div>

        <TurnstileWidget onToken={setTsToken} />

        {error && (
          <div className="text-sm rounded-ss-md border px-3 py-2 bg-[var(--ss-danger-bg)] border-[var(--ss-danger-border)] text-[var(--ss-danger-text)]">
            {error}
          </div>
        )}

        <button type="submit" disabled={loading}
                className="w-full bg-[var(--ss-brand)] hover:bg-[var(--ss-brand-hover)] text-white text-sm font-medium px-4 py-2 rounded-ss-md disabled:opacity-50 transition-colors duration-fast ease-out">
          {loading ? t('app.loading') : t('auth.register.submit')}
        </button>

        <Link to="/login" className="block text-center text-sm text-[var(--ss-brand)] hover:text-[var(--ss-brand-hover)] hover:underline">
          {t('auth.register.have_account')}
        </Link>
      </form>
    </div>
  )
}
