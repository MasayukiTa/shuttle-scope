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
  const res = await fetch(url.toString())
  if (!res.ok) {
    const text = await res.text()
    throw httpError(res.status, text)
  }
  return res.json()
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(BASE_URL + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
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
    headers: { 'Content-Type': 'application/json' },
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
  })
  if (!res.ok) {
    const text = await res.text()
    throw httpError(res.status, text)
  }
  return res.json()
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
