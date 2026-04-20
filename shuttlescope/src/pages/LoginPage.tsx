import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useAuth } from '@/hooks/useAuth'
import type { AuthSession } from '@/hooks/useAuth'
import { useTheme } from '@/hooks/useTheme'
import { UserRole } from '@/types'

const BASE_URL = (() => {
  if (
    typeof window !== 'undefined' &&
    (window.location.protocol === 'http:' || window.location.protocol === 'https:')
  ) {
    return `${window.location.origin}/api`
  }
  return 'http://localhost:8765/api'
})()

async function apiLogin(body: object): Promise<AuthSession & { error?: string }> {
  try {
    const res = await fetch(`${BASE_URL}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!res.ok) {
      const text = await res.text()
      return {
        token: '',
        role: 'player',
        userId: 0,
        playerId: null,
        teamName: null,
        displayName: null,
        error: text,
      }
    }
    const data = await res.json()
    return {
      token: data.access_token,
      role: data.role as UserRole,
      userId: data.user_id,
      playerId: data.player_id ?? null,
      teamName: data.team_name ?? null,
      displayName: data.display_name ?? null,
    }
  } catch (e) {
    return {
      token: '',
      role: 'player',
      userId: 0,
      playerId: null,
      teamName: null,
      displayName: null,
      error: String(e),
    }
  }
}

interface BootstrapStatus {
  has_admin: boolean
  bootstrap_configured: boolean
  bootstrap_username: string | null
  bootstrap_display_name: string | null
}

async function fetchBootstrapStatus(): Promise<BootstrapStatus | null> {
  try {
    const res = await fetch(`${BASE_URL}/auth/bootstrap-status`)
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}

interface Props {
  onLogin: () => void
}

export function LoginPage({ onLogin }: Props) {
  const { t } = useTranslation()
  const { setSession } = useAuth()
  const { theme } = useTheme()
  const isLight = theme === 'light'

  const [identifier, setIdentifier] = useState('')
  const [password, setPassword] = useState('')
  const [bootstrapStatus, setBootstrapStatus] = useState<BootstrapStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchBootstrapStatus().then((status) => {
      setBootstrapStatus(status)
      if (status?.bootstrap_username) {
        setIdentifier((current) => current || status.bootstrap_username || '')
      }
    })
  }, [])

  const handleLogin = async () => {
    if (!identifier.trim()) {
      setError('ID / username を入力してください')
      return
    }
    if (!password) {
      setError('パスワードまたは PIN を入力してください')
      return
    }

    setLoading(true)
    setError(null)

    const result = await apiLogin({
      grant_type: 'credential',
      identifier: identifier.trim(),
      password,
    })

    setLoading(false)
    if (result.error || !result.token) {
      setError(result.error || t('auth.error.login_failed'))
      return
    }

    setSession(result)
    onLogin()
  }

  const inputCls = isLight
    ? 'border-gray-300 bg-white text-gray-900'
    : 'border-gray-600 bg-gray-700 text-white'
  const labelCls = isLight ? 'text-gray-700' : 'text-gray-300'
  const mutedCls = isLight ? 'text-gray-500' : 'text-gray-400'
  const fieldCls = `w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${inputCls}`

  return (
    <div className={`min-h-screen flex items-center justify-center p-4 ${isLight ? 'bg-gray-100' : 'bg-gray-900'}`}>
      <div className={`rounded-xl shadow-lg w-full max-w-md p-8 ${isLight ? 'bg-white' : 'bg-gray-800'}`}>
        <div className="text-center mb-6">
          <h1 className={`text-2xl font-bold ${isLight ? 'text-gray-800' : 'text-white'}`}>ShuttleScope</h1>
          <p className={`text-sm mt-1 ${mutedCls}`}>{t('auth.subtitle')}</p>
        </div>

        {bootstrapStatus && !bootstrapStatus.has_admin && (
          <div
            className={`mb-4 border text-sm rounded-lg px-3 py-2 ${
              bootstrapStatus.bootstrap_configured
                ? (isLight
                    ? 'bg-amber-50 border-amber-200 text-amber-700'
                    : 'bg-amber-900/30 border-amber-700 text-amber-300')
                : (isLight
                    ? 'bg-red-50 border-red-200 text-red-600'
                    : 'bg-red-900/30 border-red-700 text-red-400')
            }`}
          >
            {bootstrapStatus.bootstrap_configured
              ? `初回管理者は "${bootstrapStatus.bootstrap_username ?? 'admin'}" でログインすると作成されます。`
              : '初回管理者パスワードが未設定です。BOOTSTRAP_ADMIN_PASSWORD を backend 環境変数に設定してください。'}
          </div>
        )}

        <div className="space-y-4">
          <div>
            <label className={`block text-sm font-medium mb-1 ${labelCls}`}>ID / Username</label>
            <input
              type="text"
              value={identifier}
              onChange={(e) => setIdentifier(e.target.value)}
              className={fieldCls}
              placeholder={bootstrapStatus?.bootstrap_username ?? 'admin'}
              autoComplete="username"
            />
            <p className={`mt-1 text-xs ${mutedCls}`}>
              role は不要です。ユーザー ID / username / 表示名のいずれかでログインできます。
            </p>
          </div>

          <div>
            <label className={`block text-sm font-medium mb-1 ${labelCls}`}>Password / PIN</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={fieldCls}
              onKeyDown={(e) => e.key === 'Enter' && handleLogin()}
              autoComplete="current-password"
            />
          </div>

          {error && (
            <div
              className={`border text-sm rounded-lg px-3 py-2 ${
                isLight ? 'bg-red-50 border-red-200 text-red-600' : 'bg-red-900/30 border-red-700 text-red-400'
              }`}
            >
              {error}
            </div>
          )}

          <button
            onClick={handleLogin}
            disabled={loading}
            className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-medium py-2 px-4 rounded-lg text-sm transition-colors"
          >
            {loading ? t('auth.logging_in') : t('auth.login_button')}
          </button>
        </div>
      </div>
    </div>
  )
}
