import { useState, useCallback, useEffect } from 'react'
import { UserRole } from '@/types'

const AUTH_CHANGED_EVENT = 'shuttlescope:auth-changed'

const STORAGE_KEY           = 'shuttlescope_role'
const STORAGE_KEY_PLAYER_ID = 'shuttlescope_player_id'
const STORAGE_KEY_TEAM_NAME = 'shuttlescope_team_name'

// POCフェーズ: ローカルストレージでロール管理（将来JWT認証に移行）
// 注: role=player の場合は「どの選手としてログインしたか」を player_id として保持する。
//    試合一覧や統計APIの取得時に player_id フィルタを必須化し、他選手のデータ閲覧を防ぐ。
//    （ロール自体は POC では自己申告だが、player_id により選手間の横断閲覧は塞ぐ）
function getStoredRole(): UserRole | null {
  const stored = localStorage.getItem(STORAGE_KEY)
  if (stored === 'analyst' || stored === 'coach' || stored === 'player') {
    return stored as UserRole
  }
  return null
}

function getStoredPlayerId(): number | null {
  const v = localStorage.getItem(STORAGE_KEY_PLAYER_ID)
  if (!v) return null
  const n = parseInt(v, 10)
  return Number.isFinite(n) && n > 0 ? n : null
}

function getStoredTeamName(): string | null {
  const v = localStorage.getItem(STORAGE_KEY_TEAM_NAME)
  return v && v.length > 0 ? v : null
}

export function useAuth() {
  const [role, setRoleState]         = useState<UserRole | null>(getStoredRole)
  const [playerId, setPlayerIdState] = useState<number | null>(getStoredPlayerId)
  const [teamName, setTeamNameState] = useState<string | null>(getStoredTeamName)

  useEffect(() => {
    const handler = () => {
      setRoleState(getStoredRole())
      setPlayerIdState(getStoredPlayerId())
      setTeamNameState(getStoredTeamName())
    }
    window.addEventListener(AUTH_CHANGED_EVENT, handler)
    window.addEventListener('storage', handler)
    return () => {
      window.removeEventListener(AUTH_CHANGED_EVENT, handler)
      window.removeEventListener('storage', handler)
    }
  }, [])

  const setRole = useCallback((
    newRole: UserRole,
    newPlayerId?: number | null,
    newTeamName?: string | null,
  ) => {
    localStorage.setItem(STORAGE_KEY, newRole)
    setRoleState(newRole)
    // player ロール時のみ player_id を保存。他ロールはクリアする。
    if (newRole === 'player' && typeof newPlayerId === 'number' && newPlayerId > 0) {
      localStorage.setItem(STORAGE_KEY_PLAYER_ID, String(newPlayerId))
      setPlayerIdState(newPlayerId)
    } else {
      localStorage.removeItem(STORAGE_KEY_PLAYER_ID)
      setPlayerIdState(null)
    }
    // coach ロール時のみ team_name を保存。他ロールはクリアする。
    if (newRole === 'coach' && typeof newTeamName === 'string' && newTeamName.length > 0) {
      localStorage.setItem(STORAGE_KEY_TEAM_NAME, newTeamName)
      setTeamNameState(newTeamName)
    } else {
      localStorage.removeItem(STORAGE_KEY_TEAM_NAME)
      setTeamNameState(null)
    }
    window.dispatchEvent(new Event(AUTH_CHANGED_EVENT))
  }, [])

  const clearRole = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY)
    localStorage.removeItem(STORAGE_KEY_PLAYER_ID)
    localStorage.removeItem(STORAGE_KEY_TEAM_NAME)
    setRoleState(null)
    setPlayerIdState(null)
    setTeamNameState(null)
    window.dispatchEvent(new Event(AUTH_CHANGED_EVENT))
  }, [])

  const hasRole = useCallback(
    (allowedRoles: UserRole[]) => {
      if (!role) return false
      return allowedRoles.includes(role)
    },
    [role]
  )

  return { role, playerId, teamName, setRole, clearRole, hasRole }
}

export type { UserRole }
