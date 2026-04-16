import { apiGet, apiPost } from './client'

export interface DbStats {
  supported: boolean
  file_size_mb: number
  wal_size_mb: number
  page_count: number
  freelist_count: number
  freelist_ratio: number
  auto_vacuum: number   // 0=OFF 1=FULL 2=INCREMENTAL
  page_size: number
}

export interface MaintenanceResult {
  supported: boolean
  auto_vacuum_mode: number
  freed_pages: number
  freed_mb: number
  before: DbStats
  after: DbStats
  message?: string
}

export const getDbStats = () => apiGet<DbStats>('/db/status')

export const runDbMaintenance = () => apiPost<MaintenanceResult>('/db/maintenance', {})

export const setAutoVacuum = (mode: 'incremental' | 'full' | 'off') =>
  apiPost<{ supported: boolean; changed: boolean; auto_vacuum: number; message: string; stats: DbStats; error?: string }>(
    '/db/set_auto_vacuum', { mode }
  )
