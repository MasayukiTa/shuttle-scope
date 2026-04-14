import { useState, useCallback } from 'react'
import { UserRole } from '@/types'

const STORAGE_KEY           = 'shuttlescope_role'
const STORAGE_KEY_PLAYER_ID = 'shuttlescope_player_id'

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

export function useAuth() {
  const [role, setRoleState]         = useState<UserRole | null>(getStoredRole)
  const [playerId, setPlayerIdState] = useState<number | null>(getStoredPlayerId)

  const setRole = useCallback((newRole: UserRole, newPlayerId?: number | null) => {
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
  }, [])

  const clearRole = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY)
    localStorage.removeItem(STORAGE_KEY_PLAYER_ID)
    setRoleState(null)
    setPlayerIdState(null)
  }, [])

  const hasRole = useCallback(
    (allowedRoles: UserRole[]) => {
      if (!role) return false
      return allowedRoles.includes(role)
    },
    [role]
  )

  return { role, playerId, setRole, clearRole, hasRole }
}

export type { UserRole }
