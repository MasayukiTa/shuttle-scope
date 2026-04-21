const BASE_URL = (() => {
  if (
    typeof window !== 'undefined' &&
    (window.location.protocol === 'http:' || window.location.protocol === 'https:')
  ) {
    return `${window.location.origin}/api`
  }
  return 'http://localhost:8765/api'
})()

function authHeaders(): Record<string, string> {
  const h: Record<string, string> = {}
  try {
    const token = sessionStorage.getItem('shuttlescope_token')
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

export async function apiGet<T>(
  path: string,
  params?: Record<string, string | number | boolean>
): Promise<T> {
  const url = new URL(BASE_URL + path)
  if (params) {
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, String(v)))
  }
  const res = await fetch(url.toString(), { headers: authHeaders() })
  if (!res.ok) {
    const text = await res.text()
    throw httpError(res.status, text)
  }
  return res.json()
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(BASE_URL + path, {
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
  const res = await fetch(BASE_URL + path, {
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
  const res = await fetch(BASE_URL + path, {
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
  const res = await fetch(BASE_URL + path, {
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
}

export function authMe(): Promise<AuthMeDTO> {
  return apiGet<AuthMeDTO>('/auth/me')
}

export function authLogout(): Promise<{ success: boolean }> {
  return apiPost<{ success: boolean }>('/auth/logout', {})
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
