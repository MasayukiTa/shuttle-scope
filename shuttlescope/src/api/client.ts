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

// セッション完全失効時に画面リダイレクトするためのフラグ (連続 401 で多重発火しないよう保護)
let _sessionExpiredRedirecting = false

/**
 * セッション完全失効時の処理:
 *   1. 認証情報を sessionStorage から消す
 *   2. /login へリダイレクト (HashRouter なので window.location.hash を更新)
 *   3. 既に未認証ページ (login/register/verify/camera 等) に居るならスキップ
 *
 * これにより、無操作タイムアウト後に「データが空で表示される」混乱を防ぎ、
 * 即座にログイン画面が表示される。
 */
function _handleSessionExpired(): void {
  if (typeof window === 'undefined' || _sessionExpiredRedirecting) return
  _sessionExpiredRedirecting = true
  try {
    sessionStorage.removeItem('shuttlescope_token')
    sessionStorage.removeItem(REFRESH_KEY)
    sessionStorage.removeItem('shuttlescope_role')
    sessionStorage.removeItem('shuttlescope_player_id')
    sessionStorage.removeItem('shuttlescope_team_name')
    // 残りの auth 関連 storage も全て掃除する。掃除漏れがあると `useAuth` の
    // 内部 state が "token は null だが userId/displayName は残っている" 状態
    // になり、リログイン後の表示が一貫しない。
    sessionStorage.removeItem('shuttlescope_user_id')
    sessionStorage.removeItem('shuttlescope_display_name')
    sessionStorage.removeItem('shuttlescope_page_access')
  } catch {
    /* noop */
  }
  // useAuth が listen している AUTH_CHANGED_EVENT を発火させて React state を再同期する。
  // 旧コードはこの dispatch を欠いており、`useState(() => getStored(...))` の初期値だけが
  // 残った状態で `<ProtectedMainRoute>` の `token != null` チェックを通過し続け、
  // hash が `/login?session_expired=1` に変わっても <LoginPage /> がレンダーされなかった
  // (2026-05-07 報告)。
  try {
    window.dispatchEvent(new Event(AUTH_CHANGED_EVENT))
  } catch { /* noop */ }
  // 既に未認証ページにいるならリダイレクト不要
  const currentHash = (window.location.hash || '').slice(1).split('?')[0]
  const SKIP_PATHS = [
    '/login', '/register', '/verify',
    '/password/reset', '/password/reset-confirm', '/invite',
    '/video-only', '/camera', '/viewer',
  ]
  const isOnPublicPage = SKIP_PATHS.some((p) => currentHash === p || currentHash.startsWith(p + '/'))
  if (!isOnPublicPage) {
    // HashRouter なので hash を変えるだけで遷移する。
    // クエリ session_expired=1 で LoginPage 側に「セッション切れの旨」を表示できる。
    window.location.hash = '/login?session_expired=1'
    // App ルート側が token/role を見て未ログイン状態を検出するため、
    // hash 変更だけで <LoginPage /> がレンダリングされる。
  }
  // 数秒後にフラグをリセット (再ログイン後のリクエストを通常通り扱うため)
  setTimeout(() => { _sessionExpiredRedirecting = false }, 3000)
}

async function fetchWithAutoRefresh(input: string, init: RequestInit): Promise<Response> {
  const res = await fetch(input, init)
  if (res.status !== 401) return res
  // /auth/refresh 自体が 401 の場合は再試行しない
  if (input.includes('/auth/refresh') || input.includes('/auth/login')) return res
  const ok = await tryRefreshToken()
  if (!ok) {
    // refresh も失敗 = 完全失効 → 自動でログイン画面へ
    _handleSessionExpired()
    return res
  }
  // 新 access token で再送
  const headers = { ...(init.headers as Record<string, string>), ...authHeaders() }
  return fetch(input, { ...init, headers })
}

export async function apiGet<T>(
  path: string,
  params?: Record<string, string | number | boolean | null | undefined>
): Promise<T> {
  const url = new URL(BASE_URL + path)
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v === undefined || v === null) return
      url.searchParams.set(k, String(v))
    })
  }
  const res = await fetchWithAutoRefresh(url.toString(), { headers: authHeaders() })
  if (!res.ok) {
    const text = await res.text()
    throw httpError(res.status, text)
  }
  return res.json()
}

export async function apiPost<T>(path: string, body: unknown, extraHeaders?: Record<string, string>): Promise<T> {
  const res = await fetchWithAutoRefresh(BASE_URL + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(), ...(extraHeaders ?? {}) },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const text = await res.text()
    throw httpError(res.status, text)
  }
  return res.json()
}

/**
 * 安全なランダム idempotency key を生成する。
 * Phase B2: 重要操作 (reissue, delete, export) で同じキーを送ると
 * バックエンドが 24h 以内の重複を 1 回分扱いに統合する。
 */
export function newIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID().replace(/-/g, '')
  }
  return Math.random().toString(36).slice(2) + Date.now().toString(36)
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

export async function apiDelete<T>(path: string, extraHeaders?: Record<string, string>): Promise<T> {
  const res = await fetchWithAutoRefresh(BASE_URL + path, {
    method: 'DELETE',
    headers: { ...authHeaders(), ...(extraHeaders ?? {}) },
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

// ── Phase B: チーム管理 ───────────────────────────────────────────────────
export interface TeamDTO {
  id: number
  uuid: string
  display_id: string | null
  name: string
  short_name: string | null
  is_independent: boolean
  notes: string | null
  created_at: string | null
  updated_at: string | null
}

export function listTeams(): Promise<{ success: boolean; data: TeamDTO[] }> {
  return apiGet('/auth/teams')
}

export function createTeam(body: {
  name: string
  display_id?: string | null
  short_name?: string | null
  notes?: string | null
  is_independent?: boolean
}): Promise<{ success: boolean; data: TeamDTO }> {
  return apiPost('/auth/teams', body)
}

export function patchTeam(
  teamId: number,
  body: { name?: string; display_id?: string | null; short_name?: string | null; notes?: string | null },
): Promise<{ success: boolean; data: TeamDTO }> {
  return apiPatch(`/auth/teams/${teamId}`, body)
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

export function publicInquiryDelete(
  inquiryId: number,
): Promise<{ success: boolean; data: { deleted: number } }> {
  return apiDelete(`/public/inquiries/${inquiryId}`)
}

export function publicInquiryBulkDelete(body: {
  ids?: number[]
  statuses?: Array<'new' | 'reviewed' | 'resolved'>
  created_before?: string
  created_after?: string
}): Promise<{ success: boolean; data: { deleted: number; ids: number[] } }> {
  return apiPost('/public/inquiries/bulk-delete', body)
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
