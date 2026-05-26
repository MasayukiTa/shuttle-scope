import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import i18n from '@/i18n'
import { useAuth } from '@/hooks/useAuth'
import type { AuthSession } from '@/hooks/useAuth'
import { useTheme } from '@/hooks/useTheme'
import { UserRole } from '@/types'
import { MIcon } from '@/components/common/MIcon'
import { publicSiteUrl } from '@/utils/publicUrl'

const BASE_URL = (() => {
  if (
    typeof window !== 'undefined' &&
    (window.location.protocol === 'http:' || window.location.protocol === 'https:')
  ) {
    return `${window.location.origin}/api`
  }
  return 'http://localhost:8765/api'
})()

type LoginResult =
  | (AuthSession & { mfaRequired?: false; mfaToken?: undefined; error?: string })
  | { mfaRequired: true; mfaToken: string; error?: undefined }
  | { error: string; mfaRequired?: false; mfaToken?: undefined; token?: undefined }

function _errSession(msg: string): AuthSession & { error: string } {
  return {
    token: '',
    role: 'player',
    userId: 0,
    playerId: null,
    teamName: null,
    displayName: null,
    pageAccess: [],
    error: msg,
  }
}

async function apiLogin(body: object): Promise<LoginResult> {
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
      return _errSession(errorMessage)
    }
    const data = await res.json()
    // MFA 第 2 段が必要な場合は access_token は空 / mfa_token が入る
    if (data.mfa_required && typeof data.mfa_token === 'string' && data.mfa_token) {
      return { mfaRequired: true, mfaToken: data.mfa_token }
    }
    return {
      token: data.access_token,
      refreshToken: data.refresh_token ?? null,
      role: data.role as UserRole,
      userId: data.user_id,
      playerId: data.player_id ?? null,
      teamName: data.team_name ?? null,
      displayName: data.display_name ?? null,
      pageAccess: (data.page_access ?? []) as string[],
    }
  } catch (e) {
    return _errSession(String(e))
  }
}

async function apiMfaLogin(mfaToken: string, code: string): Promise<AuthSession & { error?: string }> {
  try {
    // /api/auth/mfa/login は _GLOBAL_AUTH_EXEMPT に含まれないため
    // GlobalAuthMiddleware が Authorization: Bearer 必須。mfa_token は
    // role=mfa_pending JWT なので Bearer として送る (middleware は
    // /api/auth/mfa/* path だけ mfa_pending role を通す)。
    // body にも mfa_token を残すのはハンドラ側 verify_token が同 token を
    // 期待しているため (重複だが冗長性で安全側)。
    const res = await fetch(`${BASE_URL}/auth/mfa/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${mfaToken}`,
      },
      body: JSON.stringify({ mfa_token: mfaToken, code }),
    })
    if (!res.ok) {
      let msg = 'MFA 認証に失敗しました'
      try {
        const data = await res.json()
        if (typeof data?.detail === 'string') msg = data.detail
      } catch { /* noop */ }
      return _errSession(msg)
    }
    const data = await res.json()
    return {
      token: data.access_token,
      refreshToken: data.refresh_token ?? null,
      role: data.role as UserRole,
      userId: data.user_id,
      playerId: data.player_id ?? null,
      teamName: data.team_name ?? null,
      displayName: data.display_name ?? null,
      pageAccess: (data.page_access ?? []) as string[],
    }
  } catch (e) {
    return _errSession(String(e))
  }
}

interface BootstrapStatus {
  has_admin: boolean
  bootstrap_configured: boolean
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
  // MFA 第 2 段: credential login が mfa_required=true を返したら mfaToken を保持
  // して MFA 入力画面に切り替える。Submit で /api/auth/mfa/login を呼ぶ。
  const [mfaToken, setMfaToken] = useState<string | null>(null)
  const [mfaCode, setMfaCode] = useState('')
  // セッション期限切れリダイレクト時の通知バナー
  const sessionExpired =
    typeof window !== 'undefined' &&
    (window.location.hash || '').includes('session_expired=1')

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
    if (result.error) {
      setError(result.error)
      return
    }
    // MFA 第 2 段が必要なら 6 桁コード入力画面に切り替える
    if (result.mfaRequired) {
      setMfaToken(result.mfaToken)
      setMfaCode('')
      setError(null)
      return
    }
    if (!result.token) {
      setError(t('auth.error.login_failed'))
      return
    }

    setSession(result)
    onLogin()
  }

  const handleMfaSubmit = async () => {
    if (!mfaToken) return
    const code = mfaCode.trim()
    if (!/^\d{6}$/.test(code)) {
      setError('6 桁の数字を入力してください')
      return
    }
    setLoading(true)
    setError(null)
    const result = await apiMfaLogin(mfaToken, code)
    setLoading(false)
    if (result.error || !result.token) {
      setError(result.error || 'MFA 認証に失敗しました')
      // mfa_token が期限切れ (5 分) の場合は最初からやり直し
      if ((result.error || '').includes('期限切れ') || (result.error || '').includes('無効')) {
        setMfaToken(null)
        setMfaCode('')
      }
      return
    }
    setSession(result)
    onLogin()
  }

  const handleMfaCancel = () => {
    setMfaToken(null)
    setMfaCode('')
    setError(null)
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
          <h1 className={`text-2xl font-bold ${isLight ? 'text-gray-800' : 'text-white'}`}>{t('app.name')}</h1>
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

        {sessionExpired && (
          <div className={`mb-4 px-4 py-3 rounded text-sm ${
            isLight
              ? 'bg-amber-50 border border-amber-200 text-amber-800'
              : 'bg-amber-900/20 border border-amber-800 text-amber-200'
          }`}>
            {t('auto.LoginPage.session_expired')}
          </div>
        )}

        {mfaToken && (
          <div className="space-y-4">
            <div className={`text-sm ${mutedCls}`}>
              {t('auto.LoginPage.mfa_prompt')}
            </div>
            <div>
              <label className={`block text-sm font-medium mb-1 ${labelCls}`}>
                {t('auto.LoginPage.mfa_code_label')}
              </label>
              <input
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]*"
                maxLength={6}
                value={mfaCode}
                onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                onKeyDown={(e) => e.key === 'Enter' && handleMfaSubmit()}
                className={`${fieldCls} text-center tracking-widest text-lg font-mono`}
                placeholder="000000"
                autoFocus
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
              onClick={handleMfaSubmit}
              disabled={loading || mfaCode.length !== 6}
              className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-medium py-2 px-4 rounded-lg text-sm transition-colors"
            >
              {loading ? t('auth.logging_in') : t('auto.LoginPage.mfa_submit')}
            </button>
            <button
              onClick={handleMfaCancel}
              disabled={loading}
              className={`w-full text-sm py-2 px-4 rounded-lg transition-colors ${
                isLight
                  ? 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
                  : 'text-gray-400 hover:text-gray-200 hover:bg-gray-700'
              }`}
            >
              {t('auto.LoginPage.mfa_cancel')}
            </button>
          </div>
        )}

        {!mfaToken && (
        <div className="space-y-4">
          <div>
            <label className={`block text-sm font-medium mb-1 ${labelCls}`}>{t('auto.LoginPage.k1')}</label>
            <input
              type="text"
              value={identifier}
              onChange={(e) => setIdentifier(e.target.value)}
              className={fieldCls}
              placeholder={t('auto.LoginPage.k2')}
              autoComplete="username"
            />
          </div>

          <div>
            <label className={`block text-sm font-medium mb-1 ${labelCls}`}>{t('auto.LoginPage.password_pin')}</label>
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
                {showPassword ? <MIcon name="visibility_off" size={16} /> : <MIcon name="visibility" size={16} />}
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

          {/* M-A6: 自己サービス導線 */}
          <div className="flex flex-col sm:flex-row sm:justify-between gap-2 text-xs pt-2">
            <a href="#/register"
               className={`${isLight ? 'text-blue-600 hover:text-blue-800' : 'text-blue-400 hover:text-blue-300'} hover:underline`}>
              {t('auth.register.title')}
            </a>
            <a href="#/password/reset"
               className={`${isLight ? 'text-gray-600 hover:text-gray-900' : 'text-gray-400 hover:text-gray-200'} hover:underline`}>
              {t('auth.password_reset_request.title')}
            </a>
          </div>
        </div>
        )}
        <div className="mt-6 text-center">
          <a
            href={publicSiteUrl('/', i18n.language)}
            className={`text-sm ${isLight ? 'text-gray-500 hover:text-gray-700' : 'text-gray-400 hover:text-gray-200'} transition-colors`}
          >
            {t('auto.LoginPage.back_to_site')}
          </a>
        </div>
      </div>
    </div>
  )
}
