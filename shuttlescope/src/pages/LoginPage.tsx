import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Eye, EyeOff } from 'lucide-react'

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
      let errorMessage = 'ログインに失敗しました'
      try {
        const data = await res.json()
        const detail = typeof data?.detail === 'string' ? data.detail : ''
        if (res.status === 401) {
          errorMessage = 'IDもしくはパスワードが違います'
        } else if (detail) {
          errorMessage = detail
        }
      } catch {
        if (res.status === 401) {
          errorMessage = 'IDもしくはパスワードが違います'
        }
      }
      return {
        token: '',
        role: 'player',
        userId: 0,
        playerId: null,
        teamName: null,
        displayName: null,
        error: errorMessage,
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
  const [showPassword, setShowPassword] = useState(false)
  const [bootstrapStatus, setBootstrapStatus] = useState<BootstrapStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchBootstrapStatus().then((status) => {
      setBootstrapStatus(status)
    })
  }, [])

  const handleLogin = async () => {
    if (!identifier.trim()) {
      setError('ログインIDを入力してください')
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
              ? '初回管理者アカウントは、設定済みのログインIDとパスワードで作成されます。'
              : '初回管理者パスワードが未設定です。BOOTSTRAP_ADMIN_PASSWORD を backend 環境変数に設定してください。'}
          </div>
        )}

        <div className="space-y-4">
          <div>
            <label className={`block text-sm font-medium mb-1 ${labelCls}`}>ログインID</label>
            <input
              type="text"
              value={identifier}
              onChange={(e) => setIdentifier(e.target.value)}
              className={fieldCls}
              placeholder="ログインIDを入力"
              autoComplete="username"
            />
          </div>

          <div>
            <label className={`block text-sm font-medium mb-1 ${labelCls}`}>Password / PIN</label>
            <div className="relative">
              <input
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className={`${fieldCls} pr-11`}
                onKeyDown={(e) => e.key === 'Enter' && handleLogin()}
                autoComplete="current-password"
              />
              <button
                type="button"
                onClick={() => setShowPassword((v) => !v)}
                className={`absolute inset-y-0 right-0 flex items-center px-3 ${
                  isLight ? 'text-gray-500 hover:text-gray-700' : 'text-gray-400 hover:text-gray-200'
                }`}
                title={showPassword ? '非表示' : '表示'}
                aria-label={showPassword ? 'パスワードを隠す' : 'パスワードを表示'}
              >
                {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
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
        <div className="mt-6 text-center">
          <a
            href="https://shuttle-scope.com"
            className={`text-sm ${isLight ? 'text-gray-500 hover:text-gray-700' : 'text-gray-400 hover:text-gray-200'} transition-colors`}
          >
            ← shuttle-scope.com
          </a>
        </div>
      </div>
    </div>
  )
}
