import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import i18n from '@/i18n'
import { useAuth } from '@/hooks/useAuth'
import type { AuthSession } from '@/hooks/useAuth'
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

// code / recoveryCode はどちらか一方だけを送る。両方送るとサーバ側の
// バリデーション (1 リクエスト 2 回試行の防止) で 422 になる。
async function apiMfaLogin(
  mfaToken: string,
  code: string,
  useRecovery = false,
): Promise<AuthSession & { error?: string }> {
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
      body: JSON.stringify(
        useRecovery
          ? { mfa_token: mfaToken, recovery_code: code }
          : { mfa_token: mfaToken, code },
      ),
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

// リカバリコードは base32 由来の 16 文字 (0/1/8/9 を含まない)。
// 表示は XXXX-XXXX-XXXX-XXXX だが、入力は区切り・大小文字を問わず受ける。
const RECOVERY_CODE_LEN = 16
const RECOVERY_ALPHABET = /[A-Z2-7]/

function normalizeRecoveryInput(value: string): string {
  return value.toUpperCase().split('').filter((c) => RECOVERY_ALPHABET.test(c)).join('')
}

// 入力中も XXXX-XXXX-… の見た目を保って読み合わせしやすくする。
function formatRecoveryInput(value: string): string {
  const raw = normalizeRecoveryInput(value).slice(0, RECOVERY_CODE_LEN)
  return raw.replace(/(.{4})(?=.)/g, '$1-')
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
  // 認証アプリを失った / 端末やサーバの時計がずれて TOTP が通らない場合に
  // リカバリコード入力へ切り替える。
  const [useRecovery, setUseRecovery] = useState(false)
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
    if (useRecovery) {
      // XXXX-XXXX-XXXX-XXXX (区切りは任意)。正規化後 16 文字であればよい。
      if (normalizeRecoveryInput(code).length !== RECOVERY_CODE_LEN) {
        setError(t('auto.LoginPage.mfa_recovery_format_error'))
        return
      }
    } else if (!/^\d{6}$/.test(code)) {
      setError('6 桁の数字を入力してください')
      return
    }
    setLoading(true)
    setError(null)
    const result = await apiMfaLogin(mfaToken, code, useRecovery)
    setLoading(false)
    if (result.error || !result.token) {
      setError(result.error || 'MFA 認証に失敗しました')
      // mfa_token 自体が失効した場合のみ最初からやり直す。
      // 「認証コードが無効です」「リカバリコードが無効か…」でも巻き戻ると、
      // 打ち間違えるたびにパスワード入力からやり直しになってしまう。
      if ((result.error || '').includes('MFAトークンが無効')
          || (result.error || '').includes('期限切れ')) {
        setMfaToken(null)
        setMfaCode('')
        setUseRecovery(false)
      }
      return
    }
    setSession(result)
    onLogin()
  }

  const handleMfaCancel = () => {
    setMfaToken(null)
    setMfaCode('')
    setUseRecovery(false)
    setError(null)
  }

  // TOTP ⇄ リカバリコードの切り替え。入力欄の検証規則が変わるため入力を捨てる。
  const toggleRecoveryMode = () => {
    setUseRecovery((v) => !v)
    setMfaCode('')
    setError(null)
  }

  // v2 "Precision on Gray": ctrl トークンは globals.css の input/select/textarea
  // 共通ルールで自動適用されるため、境界線色は border-[var(--ss-ctrl-border)] のみ
  // 明示すれば足りる。focus リングも globals.css 側で処理済み。
  const labelCls = 'text-[var(--ss-t2)]'
  const mutedCls = 'text-[var(--ss-t3)]'
  const fieldCls =
    'w-full border border-[var(--ss-ctrl-border)] rounded-ss-md px-3 py-2.5 text-base min-h-[44px] ' +
    'bg-[var(--ss-ctrl-bg)] text-[var(--ss-ctrl-text)] outline-none transition-colors duration-fast ease-out'

  return (
    <div
      className="min-h-[100svh] flex items-center justify-center p-4 bg-[var(--ss-bg-app)]"
      style={{ paddingBottom: 'max(1rem, env(safe-area-inset-bottom))' }}
    >
      <div className="rounded-ss-lg shadow-card border border-[var(--ss-border)] bg-[var(--ss-surface-1)] w-full max-w-md p-6 sm:p-8">
        <div className="text-center mb-6">
          <h1 className="text-2xl font-semibold tracking-[-0.014em] text-[var(--ss-t1)]">{t('app.name')}</h1>
          <p className={`text-sm mt-1 ${mutedCls}`}>{t('auth.subtitle')}</p>
        </div>

        {bootstrapStatus && !bootstrapStatus.has_admin && (
          <div
            className={`mb-4 border text-sm rounded-ss-md px-3 py-2 ${
              bootstrapStatus.bootstrap_configured
                ? 'bg-[var(--ss-warning-bg)] border-[var(--ss-warning-border)] text-[var(--ss-warning-text)]'
                : 'bg-[var(--ss-danger-bg)] border-[var(--ss-danger-border)] text-[var(--ss-danger-text)]'
            }`}
          >
            {bootstrapStatus.bootstrap_configured
              ? '初回管理者アカウントは、設定済みのログインIDとパスワードで作成されます。'
              : '初回管理者パスワードが未設定です。BOOTSTRAP_ADMIN_PASSWORD を backend 環境変数に設定してください。'}
          </div>
        )}

        {sessionExpired && (
          <div className="mb-4 px-4 py-3 rounded-ss-md text-sm border bg-[var(--ss-warning-bg)] border-[var(--ss-warning-border)] text-[var(--ss-warning-text)]">
            {t('auto.LoginPage.session_expired')}
          </div>
        )}

        {mfaToken && (
          <div className="space-y-4">
            <div className={`text-sm ${mutedCls}`}>
              {useRecovery
                ? t('auto.LoginPage.mfa_recovery_prompt')
                : t('auto.LoginPage.mfa_prompt')}
            </div>
            <div>
              <label className={`block text-sm font-medium mb-1 ${labelCls}`}>
                {useRecovery
                  ? t('auto.LoginPage.mfa_recovery_label')
                  : t('auto.LoginPage.mfa_code_label')}
              </label>
              {useRecovery ? (
                <input
                  type="text"
                  autoComplete="one-time-code"
                  // 16 文字 + ハイフン 3 = 19
                  maxLength={19}
                  value={mfaCode}
                  onChange={(e) => setMfaCode(formatRecoveryInput(e.target.value))}
                  onKeyDown={(e) => e.key === 'Enter' && handleMfaSubmit()}
                  className={`${fieldCls} ss-num text-center tracking-widest text-lg`}
                  placeholder="XXXX-XXXX-XXXX-XXXX"
                  autoFocus
                />
              ) : (
                <input
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  pattern="[0-9]*"
                  maxLength={6}
                  value={mfaCode}
                  onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  onKeyDown={(e) => e.key === 'Enter' && handleMfaSubmit()}
                  className={`${fieldCls} ss-num text-center tracking-widest text-lg`}
                  placeholder="000000"
                  autoFocus
                />
              )}
            </div>
            {error && (
              <div className="border text-sm rounded-ss-md px-3 py-2 bg-[var(--ss-danger-bg)] border-[var(--ss-danger-border)] text-[var(--ss-danger-text)]">
                {error}
              </div>
            )}
            <button
              onClick={handleMfaSubmit}
              disabled={
                loading
                || (useRecovery
                  ? normalizeRecoveryInput(mfaCode).length !== RECOVERY_CODE_LEN
                  : mfaCode.length !== 6)
              }
              className="w-full bg-[var(--ss-brand)] hover:bg-[var(--ss-brand-hover)] disabled:opacity-50 text-white font-medium py-2 px-4 rounded-ss-md text-sm transition-colors duration-fast ease-out"
            >
              {loading ? t('auth.logging_in') : t('auto.LoginPage.mfa_submit')}
            </button>
            <button
              onClick={toggleRecoveryMode}
              disabled={loading}
              className="w-full text-sm py-2 px-4 rounded-ss-md transition-colors duration-fast ease-out text-[var(--ss-t2)] hover:text-[var(--ss-t1)] hover:bg-[var(--ss-surface-2)]"
            >
              {useRecovery
                ? t('auto.LoginPage.mfa_use_totp')
                : t('auto.LoginPage.mfa_use_recovery')}
            </button>
            <button
              onClick={handleMfaCancel}
              disabled={loading}
              className="w-full text-sm py-2 px-4 rounded-ss-md transition-colors duration-fast ease-out text-[var(--ss-t2)] hover:text-[var(--ss-t1)] hover:bg-[var(--ss-surface-2)]"
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
                className="absolute inset-y-0 right-0 flex items-center px-3 text-[var(--ss-t3)] hover:text-[var(--ss-t2)] transition-colors duration-fast ease-out"
                title={showPassword ? '非表示' : '表示'}
                aria-label={showPassword ? 'パスワードを隠す' : 'パスワードを表示'}
              >
                {showPassword ? <MIcon name="visibility_off" size={16} /> : <MIcon name="visibility" size={16} />}
              </button>
            </div>
          </div>

          {error && (
            <div className="border text-sm rounded-ss-md px-3 py-2 bg-[var(--ss-danger-bg)] border-[var(--ss-danger-border)] text-[var(--ss-danger-text)]">
              {error}
            </div>
          )}

          <button
            onClick={handleLogin}
            disabled={loading}
            className="w-full bg-[var(--ss-brand)] hover:bg-[var(--ss-brand-hover)] disabled:opacity-50 text-white font-medium py-2 px-4 rounded-ss-md text-sm transition-colors duration-fast ease-out"
          >
            {loading ? t('auth.logging_in') : t('auth.login_button')}
          </button>

          {/* M-A6: 自己サービス導線 */}
          <div className="flex flex-col sm:flex-row sm:justify-between gap-2 text-xs pt-2">
            <a href="#/register"
               className="text-[var(--ss-brand)] hover:text-[var(--ss-brand-hover)] hover:underline">
              {t('auth.register.title')}
            </a>
            <a href="#/password/reset"
               className="text-[var(--ss-t2)] hover:text-[var(--ss-t1)] hover:underline">
              {t('auth.password_reset_request.title')}
            </a>
          </div>
        </div>
        )}
        <div className="mt-6 text-center">
          <a
            href={publicSiteUrl('/', i18n.language)}
            className="text-sm text-[var(--ss-t3)] hover:text-[var(--ss-t2)] transition-colors duration-fast ease-out"
          >
            {t('auto.LoginPage.back_to_site')}
          </a>
        </div>
      </div>
    </div>
  )
}
