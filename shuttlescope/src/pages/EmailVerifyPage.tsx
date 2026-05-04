import { useEffect, useState } from 'react'
import { useSearchParams, Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { apiGet } from '@/api/client'

export default function EmailVerifyPage() {
  const { t } = useTranslation()
  const [params] = useSearchParams()
  const [status, setStatus] = useState<'loading' | 'ok' | 'error'>('loading')
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [verifiedEmail, setVerifiedEmail] = useState<string | null>(null)

  useEffect(() => {
    const token = params.get('token')
    if (!token) {
      setStatus('error')
      setErrorMsg(t('auth.verify.missing_token'))
      return
    }
    apiGet<{ success: boolean; data: { verified_email: string } }>(`/auth/email/verify?token=${encodeURIComponent(token)}`)
      .then((r) => {
        setStatus('ok')
        setVerifiedEmail(r.data?.verified_email ?? null)
      })
      .catch((err) => {
        setStatus('error')
        setErrorMsg(err?.message ?? String(err))
      })
  }, [params, t])

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900 p-4">
      <div className="max-w-md w-full bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-4 text-center">
        <h1 className="text-xl font-bold">{t('auth.verify.title')}</h1>
        {status === 'loading' && <p>{t('app.loading')}</p>}
        {status === 'ok' && (
          <>
            <p className="text-green-700 dark:text-green-400">
              ✅ {t('auth.verify.success')}
            </p>
            {verifiedEmail && (
              <p className="text-sm text-gray-600 dark:text-gray-300">{verifiedEmail}</p>
            )}
            <Link to="/login" className="block text-blue-600 hover:underline text-sm">
              {t('auth.verify.go_login')}
            </Link>
          </>
        )}
        {status === 'error' && (
          <>
            <p className="text-red-600">❌ {errorMsg ?? t('auth.verify.failed')}</p>
            <Link to="/login" className="block text-blue-600 hover:underline text-sm">
              {t('auth.verify.go_login')}
            </Link>
          </>
        )}
      </div>
    </div>
  )
}
