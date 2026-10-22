/**
 * Product telemetry: high-density event tracking with IndexedDB buffer.
 *
 * - Calls to `track()` are non-blocking. Events go to an IndexedDB queue;
 *   a flusher posts them to `/api/_telemetry/ingest` every 30 s, on tab
 *   `visibilitychange:hidden`, and on `pagehide`.
 * - Telemetry is best-effort. Network failure or backend rejection never
 *   surfaces to the UI.
 * - All identifiers sent are pseudonymous (server-side HMAC).
 *
 * Legal basis: GDPR Art 6(1)(f) legitimate interest / APPI 第18条但書.
 * Disclosed in PRIVACY.md §テレメトリ. No popup consent; Art 21 objection
 * via contact@shuttle-scope.com.
 */
import { API_BASE_URL, fetchWithTimeout, getAuthHeaders } from '@/api/client'

/** telemetry 送信の timeout (ms)。flush ロックを無期限に握らないための上限。 */
const FLUSH_TIMEOUT_MS = 15_000

// ─── event taxonomy (server-side allowlist と同期させること) ────────────
export type EventType =
  | 'session_start'
  | 'session_end'
  | 'page_view'
  | 'pass_started'
  | 'pass_completed'
  | 'pass_abandoned'
  | 'input_event'
  | 'analysis_view'
  | 'analysis_dwell'
  | 'analysis_interaction'
  | 'condition_input'
  | 'tutorial_step'
  | 'error_event'
  | 'network_slow'
  | 'ui_event'

export interface PendingEvent {
  event_id: string
  event_type: EventType
  props: Record<string, unknown>
  client_ts: number  // ms epoch
  /** 記録時のログイン利用者 (sessionStorage の user_id)。未ログイン時・旧データは無し。送信 payload には含めない。 */
  owner?: string | null
}

const DB_NAME = 'shuttlescope_telemetry'
const STORE = 'events'
const FLUSH_INTERVAL_MS = 30_000
const BATCH_SIZE = 100
/** 未送信キューの最大件数。送信が止まっても IndexedDB が増え続けないための上限。 */
export const MAX_QUEUED_EVENTS = 5000
/** 未送信イベントの保持期限 (ms)。7 日以上前の利用記録は送っても分析価値が低く、端末に残す理由も無い。 */
export const QUEUE_TTL_MS = 7 * 24 * 60 * 60 * 1000
/** TTL 掃除の最小間隔 (ms)。件数超過は毎回確認する。 */
const PRUNE_INTERVAL_MS = 60 * 60 * 1000
const APP_VERSION =
  (typeof __APP_VERSION__ !== 'undefined' ? __APP_VERSION__ : null) ||
  (typeof window !== 'undefined'
    ? (document.querySelector('meta[name="app-version"]') as HTMLMetaElement | null)?.content
    : null) ||
  'dev'

declare const __APP_VERSION__: string | undefined

let _platform: string | null = null
function detectPlatform(): string {
  if (_platform) return _platform
  try {
    if (typeof window === 'undefined') {
      _platform = 'unknown'
    } else if ((window as unknown as { electronAPI?: unknown }).electronAPI || /electron/i.test(navigator.userAgent || '')) {
      _platform = 'desktop'
    } else if ((navigator as unknown as { standalone?: boolean }).standalone || window.matchMedia('(display-mode: standalone)').matches) {
      _platform = 'mobile_pwa'
    } else if (/Mobi|Android|iPhone|iPad/i.test(navigator.userAgent || '')) {
      _platform = 'mobile_web'
    } else {
      _platform = 'desktop'
    }
  } catch {
    _platform = 'unknown'
  }
  return _platform || 'unknown'
}

function uuid(): string {
  try {
    // lib.dom では randomUUID が必須プロパティなので `in` で絞ると
    // else 側が never に落ち、フォールバックが型上だけ消える。
    // 実際には randomUUID は secure context 限定で、LAN の http:// では
    // undefined になる — このアプリが一番使う経路なので消してはいけない。
    const c: Crypto | undefined = typeof crypto !== 'undefined' ? crypto : undefined
    if (!c) throw new Error('no crypto')
    if (typeof c.randomUUID === 'function') {
      return c.randomUUID()
    }
    const buf = new Uint8Array(16)
    c.getRandomValues(buf)
    buf[6] = (buf[6] & 0x0f) | 0x40
    buf[8] = (buf[8] & 0x3f) | 0x80
    const hex = Array.from(buf).map(b => b.toString(16).padStart(2, '0')).join('')
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
  } catch {
    return `${Date.now()}-${Math.random().toString(36).slice(2)}`
  }
}

// ── IndexedDB wrapper ───────────────────────────────────────────────────
let _dbPromise: Promise<IDBDatabase> | null = null
function openDB(): Promise<IDBDatabase> {
  if (_dbPromise) return _dbPromise
  _dbPromise = new Promise((resolve, reject) => {
    try {
      const req = indexedDB.open(DB_NAME, 1)
      req.onupgradeneeded = () => {
        const db = req.result
        if (!db.objectStoreNames.contains(STORE)) {
          db.createObjectStore(STORE, { keyPath: 'event_id' })
        }
      }
      req.onsuccess = () => resolve(req.result)
      req.onerror = () => reject(req.error)
    } catch (e) {
      reject(e)
    }
  })
  return _dbPromise
}

async function enqueue(ev: PendingEvent): Promise<void> {
  try {
    const db = await openDB()
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite')
      tx.objectStore(STORE).put(ev)
      tx.oncomplete = () => resolve()
      tx.onerror = () => reject(tx.error)
    })
  } catch {
    // 失敗しても UI に影響を与えない
  }
}

/** キュー全体を読む (上限 MAX_QUEUED_EVENTS 程度なので全件でよい)。 */
async function readAll(): Promise<PendingEvent[]> {
  try {
    const db = await openDB()
    return await new Promise<PendingEvent[]>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readonly')
      const req = tx.objectStore(STORE).getAll()
      req.onsuccess = () => resolve(req.result as PendingEvent[])
      req.onerror = () => reject(req.error)
    })
  } catch {
    return []
  }
}

/** 現在ログイン中の利用者 (未ログインは null)。 */
function currentOwner(): string | null {
  try {
    return sessionStorage.getItem('shuttlescope_user_id') || null
  } catch {
    return null
  }
}

/**
 * 期限切れ (TTL 超過) と、件数上限を超えた古いものの event_id を返す。
 * 上限を超えた場合は client_ts の古い順に捨てる。
 */
export function pickPruneIds(
  events: ReadonlyArray<Pick<PendingEvent, 'event_id' | 'client_ts'>>,
  now: number,
  ttlMs: number = QUEUE_TTL_MS,
  maxCount: number = MAX_QUEUED_EVENTS,
): string[] {
  const drop = new Set<string>()
  const live: Array<Pick<PendingEvent, 'event_id' | 'client_ts'>> = []
  for (const e of events) {
    if (now - e.client_ts > ttlMs) drop.add(e.event_id)
    else live.push(e)
  }
  if (live.length > maxCount) {
    live.sort((a, b) => a.client_ts - b.client_ts)
    for (const e of live.slice(0, live.length - maxCount)) drop.add(e.event_id)
  }
  return Array.from(drop)
}

/**
 * 今送るイベントと、捨てるイベントを決める。
 * 他の利用者が記録したイベントは、現在の認証主体 (別の利用者) へ誤帰属させないため
 * 送らずに捨てる。owner 無し (未ログイン中・旧データ) は従来どおり送る。
 * 現在が未ログインなら送れないので何も捨てず保持する。
 */
export function planFlush<T extends Pick<PendingEvent, 'event_id' | 'owner'>>(
  events: ReadonlyArray<T>,
  owner: string | null,
  batchSize: number = BATCH_SIZE,
): { send: T[]; dropIds: string[] } {
  if (owner === null) return { send: events.slice(0, batchSize), dropIds: [] }
  const send: T[] = []
  const dropIds: string[] = []
  for (const e of events) {
    if (e.owner && e.owner !== owner) dropIds.push(e.event_id)
    else if (send.length < batchSize) send.push(e)
  }
  return { send, dropIds }
}

let _lastPruneAt = 0
async function pruneQueue(events: PendingEvent[]): Promise<PendingEvent[]> {
  const now = Date.now()
  if (events.length <= MAX_QUEUED_EVENTS && now - _lastPruneAt < PRUNE_INTERVAL_MS) return events
  _lastPruneAt = now
  const ids = pickPruneIds(events, now)
  if (!ids.length) return events
  await removeIds(ids)
  const gone = new Set(ids)
  return events.filter(e => !gone.has(e.event_id))
}

async function removeIds(ids: string[]): Promise<void> {
  if (!ids.length) return
  try {
    const db = await openDB()
    await new Promise<void>((resolve) => {
      const tx = db.transaction(STORE, 'readwrite')
      const store = tx.objectStore(STORE)
      for (const id of ids) store.delete(id)
      tx.oncomplete = () => resolve()
      tx.onerror = () => resolve()
    })
  } catch {
    // ignore
  }
}

// ── Public API ──────────────────────────────────────────────────────────
export function track(eventType: EventType, props: Record<string, unknown> = {}): void {
  // 同期的に enqueue (await しない、blocking 防止)
  void enqueue({
    event_id: uuid(),
    event_type: eventType,
    props,
    client_ts: Date.now(),
    owner: currentOwner(),
  })
}

/** /_telemetry/ingest の応答が「未ログインのため 0 件処理」を示すか。 */
export function wasSkippedForNoUser(body: unknown): boolean {
  if (!body || typeof body !== 'object') return false
  return (body as { skipped?: unknown }).skipped === 'no_user'
}

let _flushing = false
export async function flushNow(): Promise<void> {
  if (_flushing) return
  _flushing = true
  try {
    const queued = await pruneQueue(await readAll())
    const plan = planFlush(queued, currentOwner())
    if (plan.dropIds.length) await removeIds(plan.dropIds)
    // owner は端末内の境界確認用。サーバへは送らない。
    const events = plan.send.map(({ owner: _owner, ...rest }) => rest)
    if (!events.length) return
    const body = JSON.stringify({
      events,
      platform: detectPlatform(),
      app_version: APP_VERSION,
    })
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
    }
    let ok = false
    try {
      // sendBeacon は認証ヘッダ送れないので fetch を使う
      // 応答しない半断で _flushing が永久に固定されないよう有限 timeout を掛ける。
      const r = await fetchWithTimeout(`${API_BASE_URL}/_telemetry/ingest`, {
        method: 'POST',
        headers,
        body,
        // credentials は同一オリジン default。CORS の場合は backend が許可。
        keepalive: true,
      }, FLUSH_TIMEOUT_MS)
      ok = r.ok
      if (ok) {
        // 未ログインで受け取られなかった (inserted 0 / skipped no_user) 場合は、
        // 消さずに残す。消すと、ログイン前に積んだ session_start が失われ、
        // 直近の利用者数が 0 のままになる。
        let parsed: unknown = null
        try { parsed = await r.json() } catch { parsed = null }
        if (wasSkippedForNoUser(parsed)) ok = false
      }
    } catch {
      ok = false
    }
    if (ok) {
      await removeIds(events.map(e => e.event_id))
    }
    // 失敗時は IndexedDB に残置、次回 flush で再送
  } finally {
    _flushing = false
  }
}

// ── Auto-start: interval + visibility + pagehide ────────────────────────
let _started = false
export function startTelemetry(): void {
  if (_started || typeof window === 'undefined') return
  _started = true

  setInterval(() => { void flushNow() }, FLUSH_INTERVAL_MS)
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') void flushNow()
  })
  window.addEventListener('pagehide', () => { void flushNow() })

  // initial session_start
  track('session_start', { url: location.pathname, ts: Date.now() })

  // page_view tracking via history API
  let _lastPath = location.pathname + location.hash
  let _lastPathStart = performance.now()
  const emitPageView = () => {
    const dwell = Math.max(0, Math.round(performance.now() - _lastPathStart))
    track('page_view', { path: _lastPath, dwell_ms: dwell })
    _lastPath = location.pathname + location.hash
    _lastPathStart = performance.now()
  }
  window.addEventListener('hashchange', emitPageView)
  window.addEventListener('popstate', emitPageView)
  window.addEventListener('beforeunload', () => {
    try {
      const dwell = Math.max(0, Math.round(performance.now() - _lastPathStart))
      track('page_view', { path: _lastPath, dwell_ms: dwell, final: true })
      track('session_end', { dwell_ms: dwell })
    } catch {
      // ignore
    }
  })
}

// ── 計装用ショートカット (頻出パターン) ───────────────────────────────
export function trackPassStarted(passNo: 1 | 2 | 3, matchHash?: string): void {
  track('pass_started', { pass_no: passNo, match_hash: matchHash })
}
export function trackPassCompleted(passNo: 1 | 2 | 3, elapsedMs: number, inputCount: number): void {
  track('pass_completed', { pass_no: passNo, elapsed_ms: elapsedMs, input_count: inputCount })
}
export function trackPassAbandoned(passNo: 1 | 2 | 3, elapsedMs: number, lastInputType: string): void {
  track('pass_abandoned', { pass_no: passNo, elapsed_ms: elapsedMs, last_input_type: lastInputType })
}
export function trackInput(inputType: string, elapsedSincePrevMs: number, retryCount = 0): void {
  track('input_event', { input_type: inputType, elapsed_since_prev_ms: elapsedSincePrevMs, retry_count: retryCount })
}
export function trackAnalysisView(viewId: string, props: Record<string, unknown> = {}): void {
  track('analysis_view', { view_id: viewId, ...props })
}
export function trackAnalysisDwell(viewId: string, dwellMs: number, interactionsCount = 0, scrollDepthPct = 0): void {
  track('analysis_dwell', { view_id: viewId, dwell_ms: dwellMs, interactions_count: interactionsCount, scroll_depth_pct: scrollDepthPct })
}
export function trackAnalysisInteraction(viewId: string, action: string, target?: string, value?: unknown): void {
  track('analysis_interaction', { view_id: viewId, action, target, value })
}
export function trackConditionInput(questionId: string, elapsedMs: number, valueChangedCount = 1): void {
  track('condition_input', { question_id: questionId, elapsed_ms: elapsedMs, value_changed_count: valueChangedCount })
}
export function trackTutorialStep(tutorialId: string, stepNo: number, action: 'viewed' | 'completed' | 'skipped' | 'replayed' | 'aborted'): void {
  track('tutorial_step', { tutorial_id: tutorialId, step_no: stepNo, action })
}
export function trackError(where: string, errorKind: string, props: Record<string, unknown> = {}): void {
  track('error_event', { where, error_kind: errorKind, ...props })
}
export function trackUiEvent(componentId: string, action: string, props: Record<string, unknown> = {}): void {
  track('ui_event', { component_id: componentId, action, ...props })
}

/**
 * 分析画面の dwell を自動計測する React hook 用ヘルパー (mount/unmount 同梱)。
 * 使い方:
 *   useEffect(() => analyticsViewLifecycle('prediction.win_prob'), [])
 */
export function analyticsViewLifecycle(
  viewId: string,
  props: Record<string, unknown> = {},
): () => void {
  trackAnalysisView(viewId, props)
  const start = performance.now()
  let interactions = 0
  let maxScrollPct = 0
  const onScroll = () => {
    try {
      const sh = document.documentElement.scrollHeight - window.innerHeight
      if (sh > 0) {
        const pct = Math.round((window.scrollY / sh) * 100)
        if (pct > maxScrollPct) maxScrollPct = pct
      }
    } catch { /* ignore */ }
  }
  const onClick = () => { interactions += 1 }
  window.addEventListener('scroll', onScroll, { passive: true })
  window.addEventListener('click', onClick)
  return () => {
    window.removeEventListener('scroll', onScroll)
    window.removeEventListener('click', onClick)
    const dwell = Math.max(0, Math.round(performance.now() - start))
    trackAnalysisDwell(viewId, dwell, interactions, maxScrollPct)
  }
}
