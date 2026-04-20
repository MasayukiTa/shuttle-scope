import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '@/hooks/useAuth'
import type { AuthSession } from '@/hooks/useAuth'
import { useTheme } from '@/hooks/useTheme'
import { UserRole } from '@/types'

const BASE_URL = (() => {
  if (typeof window !== 'undefined' &&
      (window.location.protocol === 'http:' || window.location.protocol === 'https:')) {
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
      return { token: '', role: 'player', userId: 0, playerId: null, teamName: null, displayName: null, error: text }
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
    return { token: '', role: 'player', userId: 0, playerId: null, teamName: null, displayName: null, error: String(e) }
  }
}

async function fetchList(path: string): Promise<{ user_id: number; display_name: string; player_id?: number; has_pin?: boolean }[]> {
  try {
    const res = await fetch(`${BASE_URL}${path}`)
    if (!res.ok) return []
    const json = await res.json()
    return json.data ?? []
  } catch {
    return []
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

type RoleTab = 'admin' | 'analyst' | 'coach' | 'player'

interface Props {
  onLogin: () => void
}

export function LoginPage({ onLogin }: Props) {
  const { t } = useTranslation()
  const { setSession } = useAuth()
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const [tab, setTab] = useState<RoleTab>('player')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // admin
  const [adminUser, setAdminUser] = useState('')
  const [adminPass, setAdminPass] = useState('')
  const [bootstrapStatus, setBootstrapStatus] = useState<BootstrapStatus | null>(null)

  // coach
  const [coachList, setCoachList] = useState<{ user_id: number; display_name: string }[]>([])
  const [coachId, setCoachId] = useState<number | null>(null)

  // analyst
  const [analystList, setAnalystList] = useState<{ user_id: number; display_name: string; role: string }[]>([])
  const [analystId, setAnalystId] = useState<number | null>(null)

  // player
  const [playerList, setPlayerList] = useState<{ user_id: number; display_name: string; player_id?: number; has_pin?: boolean }[]>([])
  const [playerId, setPlayerId] = useState<number | null>(null)
  const [pin, setPin] = useState('')

  useEffect(() => {
    fetchBootstrapStatus().then(status => {
      setBootstrapStatus(status)
      if (status?.bootstrap_username) setAdminUser(status.bootstrap_username)
    })
    fetchList('/auth/coaches').then(list => {
      setCoachList(list)
      if (list.length > 0) setCoachId(list[0].user_id)
    })
    fetchList('/auth/analysts').then(list => {
      setAnalystList(list)
      if (list.length > 0) setAnalystId(list[0].user_id)
    })
    fetchList('/auth/players').then(list => {
      setPlayerList(list)
      if (list.length > 0) setPlayerId(list[0].user_id)
    })
  }, [])

  const handleLogin = async () => {
    setLoading(true)
    setError(null)
    let body: object

    if (tab === 'admin') {
      body = { grant_type: 'password', username: adminUser, password: adminPass }
    } else if (tab === 'analyst') {
      body = analystId
        ? { grant_type: 'select', role: 'analyst', user_id: analystId }
        : { grant_type: 'select', role: 'analyst' }
    } else if (tab === 'coach') {
      if (!coachId) { setError(t('auth.error.select_coach')); setLoading(false); return }
      body = { grant_type: 'select', role: 'coach', user_id: coachId }
    } else {
      if (!playerId) { setError(t('auth.error.select_player')); setLoading(false); return }
      body = { grant_type: 'pin', user_id: playerId, pin }
    }

    const result = await apiLogin(body)
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

  const tabClass = (r: RoleTab) =>
    `px-4 py-2 text-sm font-medium rounded-t border-b-2 transition-colors ${
      tab === r
        ? isLight
          ? 'border-blue-500 text-blue-600 bg-white'
          : 'border-blue-400 text-blue-400 bg-gray-800'
        : isLight
          ? 'border-transparent text-gray-500 hover:text-gray-700 bg-gray-50'
          : 'border-transparent text-gray-400 hover:text-gray-300 bg-gray-900'
    }`

  return (
    <div className={`min-h-screen flex items-center justify-center p-4 ${isLight ? 'bg-gray-100' : 'bg-gray-900'}`}>
      <div className={`rounded-xl shadow-lg w-full max-w-md p-8 ${isLight ? 'bg-white' : 'bg-gray-800'}`}>
        <div className="text-center mb-6">
          <h1 className={`text-2xl font-bold ${isLight ? 'text-gray-800' : 'text-white'}`}>ShuttleScope</h1>
          <p className={`text-sm mt-1 ${mutedCls}`}>{t('auth.subtitle')}</p>
        </div>

        {/* ロール選択タブ */}
        <div className={`flex border-b mb-6 gap-1 ${isLight ? 'border-gray-200' : 'border-gray-700'}`}>
          {(['player', 'coach', 'analyst', 'admin'] as RoleTab[]).map(r => (
            <button key={r} className={tabClass(r)} onClick={() => { setTab(r); setError(null) }}>
              {t(`auth.role.${r}`)}
            </button>
          ))}
        </div>

        <div className="space-y-4">
          {tab === 'admin' && (
            <>
              {bootstrapStatus && !bootstrapStatus.has_admin && (
                <div className={`border text-sm rounded-lg px-3 py-2 ${
                  bootstrapStatus.bootstrap_configured
                    ? (isLight ? 'bg-amber-50 border-amber-200 text-amber-700' : 'bg-amber-900/30 border-amber-700 text-amber-300')
                    : (isLight ? 'bg-red-50 border-red-200 text-red-600' : 'bg-red-900/30 border-red-700 text-red-400')
                }`}>
                  {bootstrapStatus.bootstrap_configured
                    ? `Initial admin will be created on first login for user "${bootstrapStatus.bootstrap_username ?? 'admin'}".`
                    : 'No admin user exists yet. Set BOOTSTRAP_ADMIN_PASSWORD in the backend environment before first admin login.'}
                </div>
              )}
              <div>
                <label className={`block text-sm font-medium mb-1 ${labelCls}`}>{t('auth.username')}</label>
                <input
                  type="text"
                  value={adminUser}
                  onChange={e => setAdminUser(e.target.value)}
                  className={fieldCls}
                  placeholder={bootstrapStatus?.bootstrap_username ?? 'admin'}
                  autoComplete="username"
                />
              </div>
              <div>
                <label className={`block text-sm font-medium mb-1 ${labelCls}`}>{t('auth.password')}</label>
                <input
                  type="password"
                  value={adminPass}
                  onChange={e => setAdminPass(e.target.value)}
                  className={fieldCls}
                  onKeyDown={e => e.key === 'Enter' && handleLogin()}
                  autoComplete="current-password"
                />
              </div>
            </>
          )}

          {tab === 'analyst' && (
            <div>
              <label className={`block text-sm font-medium mb-1 ${labelCls}`}>{t('auth.select_analyst')}</label>
              {analystList.length > 0 ? (
                <select
                  value={analystId ?? ''}
                  onChange={e => setAnalystId(Number(e.target.value))}
                  className={fieldCls}
                >
                  {analystList.map(a => (
                    <option key={a.user_id} value={a.user_id}>{a.display_name}</option>
                  ))}
                </select>
              ) : (
                <p className={`text-sm ${mutedCls}`}>{t('auth.analyst_direct')}</p>
              )}
            </div>
          )}

          {tab === 'coach' && (
            <div>
              <label className={`block text-sm font-medium mb-1 ${labelCls}`}>{t('auth.select_coach')}</label>
              {coachList.length > 0 ? (
                <select
                  value={coachId ?? ''}
                  onChange={e => setCoachId(Number(e.target.value))}
                  className={fieldCls}
                >
                  {coachList.map(c => (
                    <option key={c.user_id} value={c.user_id}>{c.display_name}</option>
                  ))}
                </select>
              ) : (
                <p className={`text-sm ${mutedCls}`}>{t('auth.no_coach_registered')}</p>
              )}
            </div>
          )}

          {tab === 'player' && (
            <>
              <div>
                <label className={`block text-sm font-medium mb-1 ${labelCls}`}>{t('auth.select_player')}</label>
                {playerList.length > 0 ? (
                  <select
                    value={playerId ?? ''}
                    onChange={e => setPlayerId(Number(e.target.value))}
                    className={fieldCls}
                  >
                    {playerList.map(p => (
                      <option key={p.user_id} value={p.user_id}>{p.display_name}</option>
                    ))}
                  </select>
                ) : (
                  <p className={`text-sm ${mutedCls}`}>{t('auth.no_player_registered')}</p>
                )}
              </div>
              <div>
                <label className={`block text-sm font-medium mb-1 ${labelCls}`}>
                  {t('auth.pin')}
                  <span className={`font-normal ml-1 ${mutedCls}`}>({t('auth.pin_optional')})</span>
                </label>
                <input
                  type="password"
                  value={pin}
                  onChange={e => setPin(e.target.value)}
                  className={fieldCls}
                  placeholder="••••"
                  onKeyDown={e => e.key === 'Enter' && handleLogin()}
                  autoComplete="current-password"
                  inputMode="numeric"
                />
              </div>
            </>
          )}

          {error && (
            <div className={`border text-sm rounded-lg px-3 py-2 ${isLight ? 'bg-red-50 border-red-200 text-red-600' : 'bg-red-900/30 border-red-700 text-red-400'}`}>
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
