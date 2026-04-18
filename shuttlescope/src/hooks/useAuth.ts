import { useState, useCallback, useEffect } from 'react'
import { UserRole } from '@/types'

const AUTH_CHANGED_EVENT = 'shuttlescope:auth-changed'

const STORAGE_KEY         = 'shuttlescope_token'
const STORAGE_KEY_ROLE    = 'shuttlescope_role'
const STORAGE_KEY_PLAYER_ID = 'shuttlescope_player_id'
const STORAGE_KEY_TEAM_NAME = 'shuttlescope_team_name'
const STORAGE_KEY_USER_ID = 'shuttlescope_user_id'
const STORAGE_KEY_DISPLAY_NAME = 'shuttlescope_display_name'

function getStored<T>(key: string, parse?: (v: string) => T): T | null {
  try {
    const v = localStorage.getItem(key)
    if (!v) return null
    return parse ? parse(v) : (v as unknown as T)
  } catch {
    return null
  }
}

function getStoredRole(): UserRole | null {
  const v = getStored<string>(STORAGE_KEY_ROLE)
  if (v === 'admin' || v === 'analyst' || v === 'coach' || v === 'player') return v as UserRole
  return null
}

function getStoredPlayerId(): number | null {
  const v = getStored<string>(STORAGE_KEY_PLAYER_ID)
  if (!v) return null
  const n = parseInt(v, 10)
  return Number.isFinite(n) && n > 0 ? n : null
}

export interface AuthSession {
  token: string
  role: UserRole
  userId: number
  playerId: number | null
  teamName: string | null
  displayName: string | null
}

export function useAuth() {
  const [token, setTokenState] = useState<string | null>(() => getStored(STORAGE_KEY))
  const [role, setRoleState] = useState<UserRole | null>(getStoredRole)
  const [playerId, setPlayerIdState] = useState<number | null>(getStoredPlayerId)
  const [teamName, setTeamNameState] = useState<string | null>(() => getStored(STORAGE_KEY_TEAM_NAME))
  const [userId, setUserIdState] = useState<number | null>(() => {
    const v = getStored<string>(STORAGE_KEY_USER_ID)
    if (!v) return null
    const n = parseInt(v, 10)
    return Number.isFinite(n) ? n : null
  })
  const [displayName, setDisplayNameState] = useState<string | null>(() => getStored(STORAGE_KEY_DISPLAY_NAME))

  useEffect(() => {
    const handler = () => {
      setTokenState(getStored(STORAGE_KEY))
      setRoleState(getStoredRole())
      setPlayerIdState(getStoredPlayerId())
      setTeamNameState(getStored(STORAGE_KEY_TEAM_NAME))
      const uid = getStored<string>(STORAGE_KEY_USER_ID)
      setUserIdState(uid ? parseInt(uid, 10) : null)
      setDisplayNameState(getStored(STORAGE_KEY_DISPLAY_NAME))
    }
    window.addEventListener(AUTH_CHANGED_EVENT, handler)
    window.addEventListener('storage', handler)
    return () => {
      window.removeEventListener(AUTH_CHANGED_EVENT, handler)
      window.removeEventListener('storage', handler)
    }
  }, [])

  const setSession = useCallback((session: AuthSession) => {
    localStorage.setItem(STORAGE_KEY, session.token)
    localStorage.setItem(STORAGE_KEY_ROLE, session.role)
    localStorage.setItem(STORAGE_KEY_USER_ID, String(session.userId))
    if (session.playerId != null) {
      localStorage.setItem(STORAGE_KEY_PLAYER_ID, String(session.playerId))
    } else {
      localStorage.removeItem(STORAGE_KEY_PLAYER_ID)
    }
    if (session.teamName) {
      localStorage.setItem(STORAGE_KEY_TEAM_NAME, session.teamName)
    } else {
      localStorage.removeItem(STORAGE_KEY_TEAM_NAME)
    }
    if (session.displayName) {
      localStorage.setItem(STORAGE_KEY_DISPLAY_NAME, session.displayName)
    } else {
      localStorage.removeItem(STORAGE_KEY_DISPLAY_NAME)
    }
    setTokenState(session.token)
    setRoleState(session.role)
    setUserIdState(session.userId)
    setPlayerIdState(session.playerId)
    setTeamNameState(session.teamName)
    setDisplayNameState(session.displayName)
    window.dispatchEvent(new Event(AUTH_CHANGED_EVENT))
  }, [])

  // 旧 POC 互換: setRole は setSession に委譲
  const setRole = useCallback((
    newRole: UserRole,
    newPlayerId?: number | null,
    newTeamName?: string | null,
  ) => {
    setSession({
      token: localStorage.getItem(STORAGE_KEY) || 'dev-no-token',
      role: newRole,
      userId: 0,
      playerId: newPlayerId ?? null,
      teamName: newTeamName ?? null,
      displayName: null,
    })
  }, [setSession])

  const clearRole = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY)
    localStorage.removeItem(STORAGE_KEY_ROLE)
    localStorage.removeItem(STORAGE_KEY_PLAYER_ID)
    localStorage.removeItem(STORAGE_KEY_TEAM_NAME)
    localStorage.removeItem(STORAGE_KEY_USER_ID)
    localStorage.removeItem(STORAGE_KEY_DISPLAY_NAME)
    setTokenState(null)
    setRoleState(null)
    setPlayerIdState(null)
    setTeamNameState(null)
    setUserIdState(null)
    setDisplayNameState(null)
    window.dispatchEvent(new Event(AUTH_CHANGED_EVENT))
  }, [])

  const hasRole = useCallback(
    (allowedRoles: UserRole[]) => {
      if (!role) return false
      // admin は全ロールの権限を持つ（player < coach < analyst <= admin）
      if (role === 'admin') return true
      return allowedRoles.includes(role)
    },
    [role]
  )

  return { token, role, playerId, teamName, userId, displayName, setRole, setSession, clearRole, hasRole }
}

export type { UserRole }
