// FastAPI HTTPクライアント
// IPC Bridgeを使わず fetch() で直接リクエスト
//
// Electron（file: / app: プロトコル）: localhost:8765 に固定
// ブラウザ（http: / https:）: window.location.origin を使用（LAN・トンネル対応）
const BASE_URL = (() => {
  if (
    typeof window !== 'undefined' &&
    (window.location.protocol === 'http:' || window.location.protocol === 'https:')
  ) {
    return `${window.location.origin}/api`
  }
  return 'http://localhost:8765/api'
})()

// ─── 認証ヘッダ ──────────────────────────────────────────────────────────────
// POCフェーズ: localStorage から現在のロール/選手IDを読んで全 HTTP リクエストに付与する。
// バックエンドは X-Role='player' の場合 X-Player-Id を match.player_* と照合してアクセス制御する。
// 将来 JWT に移行する際もここを差し替えるだけでよい。
function authHeaders(): Record<string, string> {
  const h: Record<string, string> = {}
  try {
    const role = localStorage.getItem('shuttlescope_role')
    const pid  = localStorage.getItem('shuttlescope_player_id')
    const team = localStorage.getItem('shuttlescope_team_name')
    if (role) h['X-Role'] = role
    if (pid)  h['X-Player-Id'] = pid
    if (team) h['X-Team-Name'] = encodeURIComponent(team)
  } catch { /* SSR / storage 無効環境は無視 */ }
  return h
}

// HTTP エラーに status プロパティを付与するヘルパー
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

// ─── INFRA Phase B: 解析パイプライン ─────────────────────────────────────────
// AnalysisJob のライフサイクル: queued → running → done / failed
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

// ヘルスチェック
export async function checkHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${BASE_URL}/health`)
    return res.ok
  } catch {
    return false
  }
}
