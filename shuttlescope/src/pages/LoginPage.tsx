import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '@/hooks/useAuth'
import type { AuthSession } from '@/hooks/useAuth'
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
      teamName: null,
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

type RoleTab = 'admin' | 'analyst' | 'coach' | 'player'

interface Props {
  onLogin: () => void
}

export function LoginPage({ onLogin }: Props) {
  const { t } = useTranslation()
  const { setSession } = useAuth()
  const [tab, setTab] = useState<RoleTab>('player')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // admin
  const [adminUser, setAdminUser] = useState('')
  const [adminPass, setAdminPass] = useState('')

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

  const tabClass = (t: RoleTab) =>
    `px-4 py-2 text-sm font-medium rounded-t border-b-2 transition-colors ${
      tab === t
        ? 'border-blue-500 text-blue-600 bg-white'
        : 'border-transparent text-gray-500 hover:text-gray-700 bg-gray-50'
    }`

  return (
    <div className="min-h-screen bg-gray-100 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-lg w-full max-w-md p-8">
        <div className="text-center mb-6">
          <h1 className="text-2xl font-bold text-gray-800">ShuttleScope</h1>
          <p className="text-sm text-gray-500 mt-1">{t('auth.subtitle')}</p>
        </div>

        {/* ロール選択タブ */}
        <div className="flex border-b border-gray-200 mb-6 gap-1">
          {(['player', 'coach', 'analyst', 'admin'] as RoleTab[]).map(r => (
            <button key={r} className={tabClass(r)} onClick={() => { setTab(r); setError(null) }}>
              {t(`auth.role.${r}`)}
            </button>
          ))}
        </div>

        <div className="space-y-4">
          {tab === 'admin' && (
            <>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('auth.username')}</label>
                <input
                  type="text"
                  value={adminUser}
                  onChange={e => setAdminUser(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="admin"
                  autoComplete="username"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('auth.password')}</label>
                <input
                  type="password"
                  value={adminPass}
                  onChange={e => setAdminPass(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  onKeyDown={e => e.key === 'Enter' && handleLogin()}
                  autoComplete="current-password"
                />
              </div>
            </>
          )}

          {tab === 'analyst' && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('auth.select_analyst')}</label>
              {analystList.length > 0 ? (
                <select
                  value={analystId ?? ''}
                  onChange={e => setAnalystId(Number(e.target.value))}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {analystList.map(a => (
                    <option key={a.user_id} value={a.user_id}>{a.display_name}</option>
                  ))}
                </select>
              ) : (
                <p className="text-sm text-gray-500">{t('auth.analyst_direct')}</p>
              )}
            </div>
          )}

          {tab === 'coach' && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('auth.select_coach')}</label>
              {coachList.length > 0 ? (
                <select
                  value={coachId ?? ''}
                  onChange={e => setCoachId(Number(e.target.value))}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {coachList.map(c => (
                    <option key={c.user_id} value={c.user_id}>{c.display_name}</option>
                  ))}
                </select>
              ) : (
                <p className="text-sm text-gray-500">{t('auth.no_coach_registered')}</p>
              )}
            </div>
          )}

          {tab === 'player' && (
            <>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('auth.select_player')}</label>
                {playerList.length > 0 ? (
                  <select
                    value={playerId ?? ''}
                    onChange={e => setPlayerId(Number(e.target.value))}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    {playerList.map(p => (
                      <option key={p.user_id} value={p.user_id}>{p.display_name}</option>
                    ))}
                  </select>
                ) : (
                  <p className="text-sm text-gray-500">{t('auth.no_player_registered')}</p>
                )}
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  {t('auth.pin')}
                  <span className="text-gray-400 font-normal ml-1">({t('auth.pin_optional')})</span>
                </label>
                <input
                  type="password"
                  value={pin}
                  onChange={e => setPin(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="••••"
                  onKeyDown={e => e.key === 'Enter' && handleLogin()}
                  autoComplete="current-password"
                  inputMode="numeric"
                />
              </div>
            </>
          )}

          {error && (
            <div className="bg-red-50 border border-red-200 text-red-600 text-sm rounded-lg px-3 py-2">
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
