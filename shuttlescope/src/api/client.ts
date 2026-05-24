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

// ── demo モード（チュートリアル限定 read-only 越権参照） ────────────────────
// active の間、GET リクエストに `?demo=1` を付与する。バックエンドは検証済み
// demo データのみ返すため、実データが漏れることはない（書き込みは常に拒否）。
let _demoMode = false
export function setDemoMode(on: boolean): void {
  _demoMode = on
}
export function isDemoMode(): boolean {
  return _demoMode
}

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
  // 2026-05-24 fix: 「初回ブラウザ open でいきなり session_expired=1 バナー」が
  // 出る不具合 (ユーザ報告)。原因: 完全初回 (token も refresh_token も無い)
  // でも何かの API call が 401 を返した瞬間に本関数が走り、banner flag が立つ。
  // 元々何もログインしていない状態を "session expired" と表示するのは誤り。
  // 入口で token / refresh_token のスナップショットを取り、両方とも無かった
  // ケースは「期限切れ」ではなく「未ログイン」として hash flag を立てない。
  let _hadAnyToken = false
  try {
    _hadAnyToken =
      !!sessionStorage.getItem('shuttlescope_token') ||
      !!sessionStorage.getItem(REFRESH_KEY)
  } catch {
    /* noop */
  }
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
    // ただし「元々何もログインしていなかった」場合は期限切れではなく
    // 未ログイン状態なので flag を立てずに /login のみへ遷移する。
    window.location.hash = _hadAnyToken ? '/login?session_expired=1' : '/login'
    // App ルート側が token/role を見て未ログイン状態を検出するため、
    // hash 変更だけで <LoginPage /> がレンダリングされる。
  }
  // 数秒後にフラグをリセット (再ログイン後のリクエストを通常通り扱うため)
  setTimeout(() => { _sessionExpiredRedirecting = false }, 3000)
}

/** すべての API 呼び出しに適用される既定タイムアウト (ms)。
 *  バックエンドが TCP は受けたが応答しないケース (GPU job blocking,
 *  WS deadlock, 部分障害) で UI 側 spinner が永続化する事故を防ぐ。
 *  個別呼び出しで init.signal を渡せば上書き可能。
 *  60s は長めだが file upload / 重い分析 API も通るバランス値。 */
const DEFAULT_API_TIMEOUT_MS = 60_000

/** init.signal を AbortController と統合し、既定タイムアウトを掛ける。
 *  - 呼び出し側が独自 signal を渡していたらそちらを尊重しつつ、
 *    タイムアウト signal と OR (どちらが先に発火しても abort)。
 *  - timeout で aborted の場合は明示的なエラーメッセージに置換。 */
function _withDefaultTimeout(
  input: string,
  init: RequestInit,
  timeoutMs: number = DEFAULT_API_TIMEOUT_MS,
): { init: RequestInit; cleanup: () => void; isTimeout: () => boolean } {
  const timeoutCtrl = new AbortController()
  let timedOut = false
  const timer = setTimeout(() => {
    timedOut = true
    timeoutCtrl.abort()
  }, timeoutMs)
  // 既存 signal があれば連動
  const existing = init.signal
  if (existing) {
    if (existing.aborted) {
      timeoutCtrl.abort()
    } else {
      existing.addEventListener('abort', () => timeoutCtrl.abort(), { once: true })
    }
  }
  return {
    init: { ...init, signal: timeoutCtrl.signal },
    cleanup: () => clearTimeout(timer),
    isTimeout: () => timedOut,
  }
}

async function fetchWithAutoRefresh(input: string, init: RequestInit): Promise<Response> {
  const wrap = _withDefaultTimeout(input, init)
  let res: Response
  try {
    res = await fetch(input, wrap.init)
  } catch (e) {
    wrap.cleanup()
    if (wrap.isTimeout()) {
      throw new Error(`API timeout (${DEFAULT_API_TIMEOUT_MS}ms): ${input}`, { cause: e })
    }
    throw e
  } finally {
    wrap.cleanup()
  }
  if (res.status !== 401) return res
  // /auth/refresh 自体が 401 の場合は再試行しない
  if (input.includes('/auth/refresh') || input.includes('/auth/login')) return res
  const ok = await tryRefreshToken()
  if (!ok) {
    // refresh も失敗 = 完全失効 → 自動でログイン画面へ
    _handleSessionExpired()
    return res
  }
  // 新 access token で再送 (再送にもタイムアウトを掛ける)
  const wrap2 = _withDefaultTimeout(input, {
    ...init,
    headers: { ...(init.headers as Record<string, string>), ...authHeaders() },
  })
  try {
    return await fetch(input, wrap2.init)
  } catch (e) {
    if (wrap2.isTimeout()) {
      throw new Error(`API timeout (${DEFAULT_API_TIMEOUT_MS}ms after refresh): ${input}`, { cause: e })
    }
    throw e
  } finally {
    wrap2.cleanup()
  }
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
  // demo モード中は GET に demo=1 を付与（read-only 越権参照）。
  // /tutorials/* と /auth/* は自分自身の状態取得なので付けない。
  if (_demoMode && !path.startsWith('/tutorials/') && !path.startsWith('/auth/')) {
    url.searchParams.set('demo', '1')
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
  email?: string | null
  email_verified?: boolean
  // GDPR Article 7 / APPI 第18条: 同意未取得なら frontend は OnboardingConsent へ誘導
  consent_required?: boolean
  // 任意同意のうち 1 度も回答していない type が残っているか。
  // True: popup を出す。ユーザは「あとで」も選べる。
  optional_consent_pending?: boolean
}

export function authMe(): Promise<AuthMeDTO> {
  return apiGet<AuthMeDTO>('/auth/me')
}

// ─── チュートリアル demo データ対象 ─────────────────────────────────────────
export interface TutorialDemoTarget {
  team_id: number
  player_id: number
  player_name: string
  match_id: number | null
}

export function getTutorialDemoTarget(): Promise<{ success: boolean; data: TutorialDemoTarget | null }> {
  return apiGet('/tutorials/demo-target')
}

// ─── 同意取得 (GDPR Article 7 / APPI 第18条) ────────────────────────────
export type ConsentType =
  | 'service_delivery'
  | 'beta_agreement'
  | 'ai_training'
  | 'research_participation'
  | 'cross_border_transfer'
  | 'body_disclose_to_analyst'
  | 'body_disclose_to_coach'

export interface ConsentRecord {
  consent_type: ConsentType
  consent_given: boolean
  privacy_policy_version: string
  terms_version: string
  given_at: string | null
  withdrawn_at: string | null
}

export interface ConsentStateDTO {
  consent_required: boolean
  current_versions: { privacy_policy: string; terms: string; data_contribution: string }
  required_types: ConsentType[]
  optional_types: ConsentType[]
  consents: ConsentRecord[]
  // PRIVACY §9ter: ユーザが未成年と判明している場合 True。
  // True なら AI 学習チェックを default off で表示し、注意書きを出す。
  viewer_is_minor?: boolean
}

export function getMyConsents(): Promise<{ success: boolean; data: ConsentStateDTO }> {
  return apiGet('/auth/consents')
}

export function submitConsents(payload: {
  consents: { consent_type: ConsentType; consent_given: boolean }[]
  privacy_policy_version: string
  terms_version: string
}): Promise<{ success: boolean; data: { consent_required: boolean } }> {
  return apiPost('/auth/consents', payload)
}

export function withdrawConsent(consent_type: ConsentType): Promise<{ success: boolean; data: { consent_type: ConsentType; withdrawn_at: string } }> {
  return apiDelete(`/auth/consents/${consent_type}`)
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
  ip?: string
  since?: string
  limit?: number
}): Promise<{ success: boolean; data: AuditLogEntry[] }> {
  const p: Record<string, string | number> = {}
  if (params?.action) p.action = params.action
  if (params?.user_id != null) p.user_id = params.user_id
  if (params?.ip) p.ip = params.ip
  if (params?.since) p.since = params.since
  if (params?.limit != null) p.limit = params.limit
  return apiGet('/auth/audit-logs', p)
}

export interface RequestLogEntry {
  id: number
  ts: string
  method: string
  path: string
  query: string | null
  status: number
  duration_ms: number
  user_id: number | null
  ip_addr: string | null
  xff: string | null
  ua: string | null
  request_id: string | null
  country: string | null
  source?: string | null
}

export function authRequestLogs(params?: {
  method?: string
  path_prefix?: string
  status_min?: number
  status_max?: number
  ip?: string
  user_id?: number
  source?: string
  limit?: number
}): Promise<{ success: boolean; data: RequestLogEntry[] }> {
  const p: Record<string, string | number> = {}
  if (params?.method) p.method = params.method
  if (params?.path_prefix) p.path_prefix = params.path_prefix
  if (params?.status_min != null) p.status_min = params.status_min
  if (params?.status_max != null) p.status_max = params.status_max
  if (params?.ip) p.ip = params.ip
  if (params?.user_id != null) p.user_id = params.user_id
  if (params?.source) p.source = params.source
  if (params?.limit != null) p.limit = params.limit
  return apiGet('/auth/audit-logs/request', p)
}

export interface SecurityEventEntry {
  id: number
  ts: string
  event_type: string
  severity: string
  ip_addr: string | null
  user_id: number | null
  path: string | null
  method: string | null
  ua: string | null
  request_id: string | null
  details: string | null
}

export function authSecurityEvents(params?: {
  event_type?: string
  severity?: string
  ip?: string
  limit?: number
}): Promise<{ success: boolean; data: SecurityEventEntry[] }> {
  const p: Record<string, string | number> = {}
  if (params?.event_type) p.event_type = params.event_type
  if (params?.severity) p.severity = params.severity
  if (params?.ip) p.ip = params.ip
  if (params?.limit != null) p.limit = params.limit
  return apiGet('/auth/audit-logs/security', p)
}

export interface ErrorLogEntry {
  id: number
  ts: string
  request_id: string | null
  method: string | null
  path: string | null
  status: number | null
  exc_type: string | null
  message: string | null
  traceback: string | null
  input_repr: string | null
  internal_code: string | null
  user_id: number | null
  ip_addr: string | null
}

export function authErrorLogs(params?: {
  exc_type?: string
  path_prefix?: string
  request_id?: string
  limit?: number
}): Promise<{ success: boolean; data: ErrorLogEntry[] }> {
  const p: Record<string, string | number> = {}
  if (params?.exc_type) p.exc_type = params.exc_type
  if (params?.path_prefix) p.path_prefix = params.path_prefix
  if (params?.request_id) p.request_id = params.request_id
  if (params?.limit != null) p.limit = params.limit
  return apiGet('/auth/audit-logs/errors', p)
}

export interface AuditLogActionItem {
  action: string
  count: number
}

export function authAuditLogActions(): Promise<{ success: boolean; data: AuditLogActionItem[] }> {
  return apiGet('/auth/audit-logs/actions')
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

export interface TeamDependencies {
  team_id: number
  team_name: string
  counts: { users: number; players: number; matches: number }
}

export function getTeamDependencies(
  teamId: number,
): Promise<{ success: boolean; data: TeamDependencies }> {
  return apiGet(`/auth/teams/${teamId}/dependencies`)
}

/**
 * チーム削除 (admin のみ).
 * - force=false (既定): 依存レコード (users/players/matches) があれば 409 で拒否
 *   ({ counts } を含む detail を返却)
 * - force=true: 紐付く team_id を NULL にして孤児化したうえで soft-delete
 */
export function deleteTeam(
  teamId: number,
  force: boolean = false,
): Promise<{
  success: boolean
  data: {
    team_id: number
    deleted_at: string | null
    force: boolean
    orphaned: { users: number; players: number; matches: number }
  }
}> {
  return apiDelete(`/auth/teams/${teamId}${force ? '?force=true' : ''}`)
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
  /** R42: 問い合わせ種別。"general" / "ban_appeal" 等。
   *  ban_appeal は WAF 誤 ban 申し立てチャネルからの投稿で UI で目立つ表示にする。 */
  category?: string
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
