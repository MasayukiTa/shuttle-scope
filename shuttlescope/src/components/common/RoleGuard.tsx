import React from 'react'
import { UserRole } from '@/types'
import { useAuth } from '@/hooks/useAuth'

interface RoleGuardProps {
  allowedRoles: UserRole[]
  children: React.ReactNode
  fallback?: React.ReactNode
}

/**
 * ロールガード
 * 使用例:
 * <RoleGuard allowedRoles={["analyst", "coach"]} fallback={null}>
 *   <EPVChart />
 * </RoleGuard>
 */
export function RoleGuard({ allowedRoles, children, fallback = null }: RoleGuardProps) {
  const { hasRole } = useAuth()

  if (!hasRole(allowedRoles)) {
    return <>{fallback}</>
  }

  return <>{children}</>
}
