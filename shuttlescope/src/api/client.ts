const BASE_URL = (() => {
  if (
    typeof window !== 'undefined' &&
    (window.location.protocol === 'http:' || window.location.protocol === 'https:')
  ) {
    return `${window.location.origin}/api`
  }
  return 'http://localhost:8765/api'
})()

const TOKEN_KEY = 'shuttlescope_token'
const REFRESH_KEY = 'shuttlescope_refresh_token'
const AUTH_CHANGED_EVENT = 'shuttlescope:auth-changed'

export const API_BASE_URL = BASE_URL

export function getAuthHeaders(): Record<string, string> {
  return authHeaders()
}

function authHeaders(): Record<string, string> {
  const h: Record<string, string> = {}
  try {
    const token = sessionStorage.getItem(TOKEN_KEY)
    if (token) {
      h['Authorization'] = `Bearer ${token}`
    } else {
      const role = sessionStorage.getItem('shuttlescope_role')
      const pid = sessionStorage.getItem('shuttlescope_player_id')
      const team = sessionStorage.getItem('shuttlescope_team_name')
      if (role) h['X-Role'] = role
      if (pid) h['X-Player-Id'] = pid
      if (team) h['X-Team-Name'] = encodeURIComponent(team)
    }
  } catch {
    // ignore missing storage access
  }
  return h
}

function httpError(status: number, text: string): Error {
  const err = new Error(text) as Error & { status: number }
  err.status = status
  return err
}

// ── Refresh token 自動更新（同時多発 401 を 1 本にまとめる） ─────────────
let _refreshInflight: Promise<boolean> | null = null

async function tryRefreshToken(): Promise<boolean> {
  if (_refreshInflight) return _refreshInflight
  _refreshInflight = (async () => {
    try {
      const rt = sessionStorage.getItem(REFRESH_KEY)
      if (!rt) return false
      const res = await fetch(`${BASE_URL}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: rt }),
      })
      if (!res.ok) {
        sessionStorage.removeItem(TOKEN_KEY)
        sessionStorage.removeItem(REFRESH_KEY)
        try { window.dispatchEvent(new Event(AUTH_CHANGED_EVENT)) } catch {}
        return false
      }
      const data: { access_token: string; refresh_token: string } = await res.json()
      sessionStorage.setItem(TOKEN_KEY, data.access_token)
      sessionStorage.setItem(REFRESH_KEY, data.refresh_token)
      try { window.dispatchEvent(new Event(AUTH_CHANGED_EVENT)) } catch {}
      return true
    } catch {
      return false
    } finally {
      // 次の 401 バッチに備えて解放（成功時の値は短命キャッシュしない）
      setTimeout(() => { _refreshInflight = null }, 0)
    }
  })()
  return _refreshInflight
}

async function fetchWithAutoRefresh(input: string, init: RequestInit): Promise<Response> {
  const res = await fetch(input, init)
  if (res.status !== 401) return res
  // /auth/refresh 自体が 401 の場合は再試行しない
  if (input.includes('/auth/refresh') || input.includes('/auth/login')) return res
  const ok = await tryRefreshToken()
  if (!ok) return res
  // 新 access token で再送
  const headers = { ...(init.headers as Record<string, string>), ...authHeaders() }
  return fetch(input, { ...init, headers })
}

export async function apiGet<T>(
  path: string,
  params?: Record<string, string | number | boolean>
): Promise<T> {
  const url = new URL(BASE_URL + path)
  if (params) {
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, String(v)))
  }
  const res = await fetchWithAutoRefresh(url.toString(), { headers: authHeaders() })
  if (!res.ok) {
    const text = await res.text()
    throw httpError(res.status, text)
  }
  return res.json()
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetchWithAutoRefresh(BASE_URL + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const text = await res.text()
    throw httpError(res.status, text)
  }
  return res.json()
}

export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  const res = await fetchWithAutoRefresh(BASE_URL + path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const text = await res.text()
    throw httpError(res.status, text)
  }
  return res.json()
}

export async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetchWithAutoRefresh(BASE_URL + path, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const text = await res.text()
    throw httpError(res.status, text)
  }
  return res.json()
}

export async function apiDelete<T>(path: string): Promise<T> {
  const res = await fetchWithAutoRefresh(BASE_URL + path, {
    method: 'DELETE',
    headers: authHeaders(),
  })
  if (!res.ok) {
    const text = await res.text()
    throw httpError(res.status, text)
  }
  return res.json()
}

export interface AuthMeDTO {
  role: 'admin' | 'analyst' | 'coach' | 'player'
  user_id: number | null
  player_id: number | null
  team_name: string | null
  display_name: string | null
  page_access: string[]
}

export function authMe(): Promise<AuthMeDTO> {
  return apiGet<AuthMeDTO>('/auth/me')
}

export function getUserPageAccess(userId: number): Promise<{ success: boolean; data: string[] }> {
  return apiGet(`/auth/users/${userId}/page-access`)
}

export function setUserPageAccess(userId: number, pageKeys: string[]): Promise<{ success: boolean; data: string[] }> {
  return apiPut(`/auth/users/${userId}/page-access`, { page_keys: pageKeys })
}

export function getTeamPageAccess(teamName: string): Promise<{ success: boolean; data: string[] }> {
  return apiGet(`/auth/teams/${encodeURIComponent(teamName)}/page-access`)
}

export function setTeamPageAccess(teamName: string, pageKeys: string[]): Promise<{ success: boolean; data: string[] }> {
  return apiPut(`/auth/teams/${encodeURIComponent(teamName)}/page-access`, { page_keys: pageKeys })
}

export function authChangePassword(current_password: string, new_password: string): Promise<{ success: boolean }> {
  return apiPost('/auth/password', { current_password, new_password })
}

export function authAdminResetPassword(userId: number): Promise<{ temporary_password: string }> {
  return apiPost(`/auth/users/${userId}/reset-password`, {})
}

export interface AuditLogEntry {
  id: number
  user_id: number | null
  username: string | null
  action: string
  resource_type: string | null
  resource_id: number | null
  details: string | null
  ip_addr: string | null
  created_at: string
}

export function authAuditLogs(params?: {
  action?: string
  user_id?: number
  since?: string
  limit?: number
}): Promise<{ success: boolean; data: AuditLogEntry[] }> {
  const p: Record<string, string | number> = {}
  if (params?.action) p.action = params.action
  if (params?.user_id != null) p.user_id = params.user_id
  if (params?.since) p.since = params.since
  if (params?.limit != null) p.limit = params.limit
  return apiGet('/auth/audit-logs', p)
}

export function authLogout(): Promise<{ success: boolean }> {
  const rt = (() => { try { return sessionStorage.getItem(REFRESH_KEY) } catch { return null } })()
  return apiPost<{ success: boolean }>('/auth/logout', rt ? { refresh_token: rt } : {})
}

export interface PublicInquiryRow {
  id: number
  name: string
  organization: string | null
  role: string | null
  contact_reference: string | null
  message: string
  status: 'new' | 'reviewed' | 'resolved'
  admin_note: string | null
  created_at: string
}

export function publicInquiryUnreadCount(): Promise<{ success: boolean; data: { count: number } }> {
  return apiGet('/public/inquiries/unread-count')
}

export function publicInquiryList(): Promise<{ success: boolean; data: PublicInquiryRow[] }> {
  return apiGet('/public/inquiries')
}

export function publicInquiryUpdate(
  inquiryId: number,
  body: { status: 'new' | 'reviewed' | 'resolved'; admin_note?: string | null }
): Promise<{ success: boolean }> {
  return apiPatch(`/public/inquiries/${inquiryId}`, body)
}

export interface AnalysisJobDTO {
  id: number
  match_id: number
  job_type: string
  status: 'queued' | 'running' | 'done' | 'failed'
  progress: number
  error?: string | null
  enqueued_at?: string | null
  started_at?: string | null
  finished_at?: string | null
  worker_host?: string | null
}

export function pipelineRun(match_id: number, job_type = 'full_pipeline'): Promise<AnalysisJobDTO> {
  return apiPost<AnalysisJobDTO>('/v1/pipeline/run', { match_id, job_type })
}

export function pipelineJobs(params?: { match_id?: number; status?: string; limit?: number }): Promise<AnalysisJobDTO[]> {
  const p: Record<string, string | number> = {}
  if (params?.match_id != null) p.match_id = params.match_id
  if (params?.status) p.status = params.status
  if (params?.limit) p.limit = params.limit
  return apiGet<AnalysisJobDTO[]>('/v1/pipeline/jobs', p)
}

export function pipelineJob(job_id: number): Promise<AnalysisJobDTO> {
  return apiGet<AnalysisJobDTO>(`/v1/pipeline/jobs/${job_id}`)
}

export async function checkHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${BASE_URL}/health`)
    return res.ok
  } catch {
    return false
  }
}
