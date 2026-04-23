import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { KeyRound } from 'lucide-react'
import { authChangePassword } from '@/api/client'

interface Props {
  isLight: boolean
}

export function PasswordChangeCard({ isLight }: Props) {
  const { t } = useTranslation()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  const textHeading = isLight ? 'text-gray-900' : 'text-white'
  const textMuted = isLight ? 'text-gray-500' : 'text-gray-400'
  const textSecondary = isLight ? 'text-gray-600' : 'text-gray-300'
  const inputCls = `${isLight ? 'bg-white border-gray-300 text-gray-900' : 'bg-gray-800 border-gray-600 text-white'} border rounded px-3 py-2`

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setDone(false)
    if (next !== confirm) {
      setError(t('auth.password_change.mismatch'))
      return
    }
    setBusy(true)
    try {
      await authChangePassword(current, next)
      setDone(true)
      setCurrent('')
      setNext('')
      setConfirm('')
    } catch (err) {
      const e = err as Error & { status?: number }
      setError(e.message || 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section>
      <h2 className={`text-lg font-medium ${textHeading} mb-1 flex items-center gap-2`}>
        <KeyRound size={16} />
        {t('auth.password_change.title')}
      </h2>
      <p className={`text-xs ${textMuted} mb-3`}>{t('auth.password_change.hint')}</p>
      <form onSubmit={submit} className="flex flex-col gap-2">
        <label className={`text-sm ${textSecondary}`}>{t('auth.password_change.current')}</label>
        <input
          type="password"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
          required
          className={inputCls}
          autoComplete="current-password"
        />
        <label className={`text-sm ${textSecondary} mt-2`}>{t('auth.password_change.new')}</label>
        <input
          type="password"
          value={next}
          onChange={(e) => setNext(e.target.value)}
          required
          className={inputCls}
          autoComplete="new-password"
        />
        <label className={`text-sm ${textSecondary} mt-2`}>{t('auth.password_change.confirm')}</label>
        <input
          type="password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          required
          className={inputCls}
          autoComplete="new-password"
        />
        <p className={`text-xs ${textMuted} mt-1`}>{t('auth.password_change.requirements')}</p>
        {error && <div className="text-sm text-red-400">{error}</div>}
        {done && <div className="text-sm text-green-400">{t('auth.password_change.success')}</div>}
        <button
          type="submit"
          disabled={busy}
          className={`mt-2 px-4 py-2 rounded font-medium text-sm ${
            isLight ? 'bg-blue-600 hover:bg-blue-500 text-white' : 'bg-blue-700 hover:bg-blue-600 text-white'
          } disabled:opacity-50`}
        >
          {busy ? t('auth.password_change.submitting') : t('auth.password_change.submit')}
        </button>
      </form>
    </section>
  )
}
