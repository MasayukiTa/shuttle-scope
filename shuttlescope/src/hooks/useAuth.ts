import { useState, useCallback, useEffect } from 'react'
import { UserRole } from '@/types'

const AUTH_CHANGED_EVENT = 'shuttlescope:auth-changed'

const STORAGE_KEY = 'shuttlescope_token'
const STORAGE_KEY_ROLE = 'shuttlescope_role'
const STORAGE_KEY_PLAYER_ID = 'shuttlescope_player_id'
const STORAGE_KEY_TEAM_NAME = 'shuttlescope_team_name'
const STORAGE_KEY_USER_ID = 'shuttlescope_user_id'
const STORAGE_KEY_DISPLAY_NAME = 'shuttlescope_display_name'

function readStorage(key: string): string | null {
  try {
    return sessionStorage.getItem(key)
  } catch {
    return null
  }
}

function writeStorage(key: string, value: string): void {
  try {
    sessionStorage.setItem(key, value)
  } catch {
    // ignore storage failures and keep in-memory state authoritative for this render
  }
}

function removeStorage(key: string): void {
  try {
    sessionStorage.removeItem(key)
  } catch {
    // ignore
  }
}

function getStored<T>(key: string, parse?: (v: string) => T): T | null {
  try {
    const v = readStorage(key)
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
    return () => {
      window.removeEventListener(AUTH_CHANGED_EVENT, handler)
    }
  }, [])

  const setSession = useCallback((session: AuthSession) => {
    writeStorage(STORAGE_KEY, session.token)
    writeStorage(STORAGE_KEY_ROLE, session.role)
    writeStorage(STORAGE_KEY_USER_ID, String(session.userId))
    if (session.playerId != null) {
      writeStorage(STORAGE_KEY_PLAYER_ID, String(session.playerId))
    } else {
      removeStorage(STORAGE_KEY_PLAYER_ID)
    }
    if (session.teamName) {
      writeStorage(STORAGE_KEY_TEAM_NAME, session.teamName)
    } else {
      removeStorage(STORAGE_KEY_TEAM_NAME)
    }
    if (session.displayName) {
      writeStorage(STORAGE_KEY_DISPLAY_NAME, session.displayName)
    } else {
      removeStorage(STORAGE_KEY_DISPLAY_NAME)
    }
    setTokenState(session.token)
    setRoleState(session.role)
    setUserIdState(session.userId)
    setPlayerIdState(session.playerId)
    setTeamNameState(session.teamName)
    setDisplayNameState(session.displayName)
    window.dispatchEvent(new Event(AUTH_CHANGED_EVENT))
  }, [])

  const clearRole = useCallback(() => {
    removeStorage(STORAGE_KEY)
    removeStorage(STORAGE_KEY_ROLE)
    removeStorage(STORAGE_KEY_PLAYER_ID)
    removeStorage(STORAGE_KEY_TEAM_NAME)
    removeStorage(STORAGE_KEY_USER_ID)
    removeStorage(STORAGE_KEY_DISPLAY_NAME)
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
      if (role === 'admin') return true
      return allowedRoles.includes(role)
    },
    [role]
  )

  return { token, role, playerId, teamName, userId, displayName, setSession, clearRole, hasRole }
}

export type { UserRole }
