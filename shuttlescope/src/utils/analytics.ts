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
import { API_BASE_URL, getAuthHeaders } from '@/api/client'

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

interface PendingEvent {
  event_id: string
  event_type: EventType
  props: Record<string, unknown>
  client_ts: number  // ms epoch
}

const DB_NAME = 'shuttlescope_telemetry'
const STORE = 'events'
const FLUSH_INTERVAL_MS = 30_000
const BATCH_SIZE = 100
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
    if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
      return (crypto as Crypto & { randomUUID: () => string }).randomUUID()
    }
    const buf = new Uint8Array(16)
    crypto.getRandomValues(buf)
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

async function drain(limit: number): Promise<PendingEvent[]> {
  try {
    const db = await openDB()
    return await new Promise<PendingEvent[]>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readonly')
      const req = tx.objectStore(STORE).getAll(undefined, limit)
      req.onsuccess = () => resolve(req.result as PendingEvent[])
      req.onerror = () => reject(req.error)
    })
  } catch {
    return []
  }
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
  })
}

let _flushing = false
export async function flushNow(): Promise<void> {
  if (_flushing) return
  _flushing = true
  try {
    const events = await drain(BATCH_SIZE)
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
      const r = await fetch(`${API_BASE_URL}/_telemetry/ingest`, {
        method: 'POST',
        headers,
        body,
        // credentials は同一オリジン default。CORS の場合は backend が許可。
        keepalive: true,
      })
      ok = r.ok
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
export function trackTutorialStep(tutorialId: string, stepNo: number, action: 'viewed' | 'completed' | 'skipped' | 'replayed'): void {
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
