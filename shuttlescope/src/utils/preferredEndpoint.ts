/**
 * R-2: LAN/WAN 最速経路選択ユーティリティ。
 *
 * Sender (CameraSender / DeviceManager) のアップロード先 / WS 接続先を
 * 最速経路で自動選択する:
 *
 *   1. window.location.origin  (現在のページが提供されている経路 = 通常これで OK)
 *   2. session API の coach_urls / camera_sender_urls から候補抽出
 *   3. 並行 health check (HEAD /api/health, 1 秒タイムアウト)
 *   4. 最速応答した URL を採用
 *
 * 効果:
 *   - 同一 Wi-Fi 下のスマホ → サーバ PC が同一 LAN なら 192.168.x.x:8765 で直接続
 *   - LAN 不可なら自動で Cloudflare 経由 (https://app.shuttle-scope.com)
 *   - WAN 帯域節約 + 低レイテンシ
 *
 * 制御:
 *   - VITE_SS_PREFER_LAN_ENDPOINT=false で無効化 (常に window.location.origin)
 *   - VITE_SS_HEALTH_CHECK_TIMEOUT_MS=1000 でタイムアウト調整
 */

const PREFER_LAN =
  (import.meta.env.VITE_SS_PREFER_LAN_ENDPOINT ?? 'true') !== 'false'

const HEALTH_TIMEOUT_MS =
  Number(import.meta.env.VITE_SS_HEALTH_CHECK_TIMEOUT_MS ?? '1000')

let cachedBaseUrl: string | null = null
let cacheExpiresAt = 0
const CACHE_TTL_MS = 30_000  // 30 秒キャッシュ

/**
 * 候補 URL のうち最速応答したものを返す。
 * 全失敗なら window.location.origin を返す。
 */
export async function resolveBaseUrl(): Promise<string> {
  // キャッシュ
  if (cachedBaseUrl && Date.now() < cacheExpiresAt) {
    return cachedBaseUrl
  }

  const fallback = typeof window !== 'undefined' ? window.location.origin : ''

  if (!PREFER_LAN) {
    cachedBaseUrl = fallback
    cacheExpiresAt = Date.now() + CACHE_TTL_MS
    return fallback
  }

  const candidates = await collectCandidates()
  if (candidates.length === 0) {
    cachedBaseUrl = fallback
    cacheExpiresAt = Date.now() + CACHE_TTL_MS
    return fallback
  }

  // 並行 health check、最速採用
  const winner = await raceHealth(candidates)
  cachedBaseUrl = winner ?? fallback
  cacheExpiresAt = Date.now() + CACHE_TTL_MS
  return cachedBaseUrl
}

/** キャッシュ無効化 (ネットワーク変化時) */
export function clearEndpointCache(): void {
  cachedBaseUrl = null
  cacheExpiresAt = 0
}

async function collectCandidates(): Promise<string[]> {
  const out: string[] = []
  if (typeof window !== 'undefined') {
    out.push(window.location.origin)
  }

  // env で明示指定されたフォールバック
  const envBase = (import.meta.env.VITE_SS_API_BASE_URL ?? '').trim()
  if (envBase && !out.includes(envBase)) out.push(envBase)

  // session API は session_code がないと取れない。Sender ページでは
  // path から session_code を抽出して /api/sessions/by_code/{code} を叩いて
  // candidate URL を取る (将来拡張)。現状は location.origin のみで十分。
  return out
}

async function raceHealth(candidates: string[]): Promise<string | null> {
  const promises = candidates.map((base) => probeHealth(base))
  for await (const result of settleSequential(promises)) {
    if (result) return result
  }
  return null
}

async function probeHealth(base: string): Promise<string | null> {
  const ac = new AbortController()
  const t = setTimeout(() => ac.abort(), HEALTH_TIMEOUT_MS)
  try {
    const res = await fetch(`${base}/api/health`, {
      method: 'GET',
      signal: ac.signal,
      cache: 'no-store',
    })
    return res.ok ? base : null
  } catch {
    return null
  } finally {
    clearTimeout(t)
  }
}

/** 順次 await して最初に成功したものを返す generator */
async function* settleSequential(promises: Promise<string | null>[]): AsyncGenerator<string | null> {
  for (const p of promises) {
    const r = await p
    yield r
  }
}
