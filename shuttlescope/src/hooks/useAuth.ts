import { useState, useCallback } from 'react'
import { UserRole } from '@/types'

const STORAGE_KEY = 'shuttlescope_role'

// POCフェーズ: ローカルストレージでロール管理（将来JWT認証に移行）
function getStoredRole(): UserRole | null {
  const stored = localStorage.getItem(STORAGE_KEY)
  if (stored === 'analyst' || stored === 'coach' || stored === 'player') {
    return stored as UserRole
  }
  return null
}

export function useAuth() {
  const [role, setRoleState] = useState<UserRole | null>(getStoredRole)

  const setRole = useCallback((newRole: UserRole) => {
    localStorage.setItem(STORAGE_KEY, newRole)
    setRoleState(newRole)
  }, [])

  const clearRole = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY)
    setRoleState(null)
  }, [])

  const hasRole = useCallback(
    (allowedRoles: UserRole[]) => {
      if (!role) return false
      return allowedRoles.includes(role)
    },
    [role]
  )

  return { role, setRole, clearRole, hasRole }
}

export type { UserRole }
