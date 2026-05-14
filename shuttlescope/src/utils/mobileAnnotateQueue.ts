/**
 * Mobile annotation の冗長キャッシュ + 送信キュー (R48 step 2)
 *
 * iOS Safari は通信が極端に不安定で、特に:
 *   - スリープ / バックグラウンドへ移行で fetch が aborted になる
 *   - 弱電波エリア (実業団の練習場、地下、車内) で複数秒の stall
 *   - cellular ↔ Wi-Fi 切替で TCP セッション切れ
 *
 * 「各入力ごとに即サーバ保存」を満たすには、単純な await fetch では入力ロス
 * が起きる。**選手の貴重な入力を絶対に消さない**ことを最優先にする。
 *
 * 設計:
 *   - 各入力 (createRally / updateRally / createStroke / updateStroke 等) を
 *     `enqueue()` で IndexedDB に永続化 (= ローカル冗長キャッシュ)
 *   - background ワーカー的に flush() が定期的に未送信 entry を取り出して送信
 *   - 失敗時は exponential backoff で再送 (1s, 2s, 5s, 15s, 60s, 5min, 30min)
 *   - 送信成功 = DB から削除
 *   - アプリ再起動でも IndexedDB に残るので失われない
 *   - 失敗回数が一定を超えたら "manual_retry" マークを付け、UI に通知
 *
 * 公開 API:
 *   - enqueue(item)  → 即 ID 返し (ローカル commit 済として扱える)
 *   - startBackgroundFlush()  → アプリ起動時に呼ぶ
 *   - getStatus()  → UI に「未送信 N 件 / 失敗 M 件」を出す用
 */

export type QueueEndpoint =
  | 'POST /api/rallies'
  | 'PATCH /api/rallies/:id'
  | 'DELETE /api/rallies/:id'
  | 'POST /api/strokes?rally_id=:rally_id'
  | 'PUT /api/strokes/:id'
  | 'DELETE /api/strokes/:id'
  | 'PUT /api/rallies/:id'
  | 'PATCH /api/matches/:id/video_crop'

export interface QueueItem {
  /** ローカル primary key (= IndexedDB の autoincrement) */
  localId?: number
  /** UI 側で immediate id として使う UUID (サーバ id とは別) */
  clientUuid: string
  /** REST endpoint (path にはプレースホルダ含む) */
  endpoint: QueueEndpoint
  /** path placeholder の解決値 (e.g. {id: 42}) */
  pathParams?: Record<string, string | number>
  /** body */
  body?: Record<string, unknown>
  /** 試行回数 */
  attempts: number
  /** 最後の試行時刻 (epoch ms) */
  lastAttemptAt?: number
  /** 次回再試行スケジュール (epoch ms) */
  nextAttemptAt: number
  /** 送信失敗時の最終 HTTP status (forensic 用) */
  lastStatus?: number
  /** 失敗 reason 抜粋 */
  lastError?: string
  /** 強制的にユーザの再試行 action を待つ */
  manualRetry: boolean
  /** queued 時刻 */
  queuedAt: number
}

const DB_NAME = 'shuttlescope-mobile-annot'
const DB_VERSION = 1
const STORE_QUEUE = 'queue'

let _db: IDBDatabase | null = null

function openDb(): Promise<IDBDatabase> {
  if (_db) return Promise.resolve(_db)
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains(STORE_QUEUE)) {
        const store = db.createObjectStore(STORE_QUEUE, {
          keyPath: 'localId',
          autoIncrement: true,
        })
        store.createIndex('byNextAttempt', 'nextAttemptAt')
        store.createIndex('byUuid', 'clientUuid', { unique: false })
      }
    }
    req.onsuccess = () => {
      _db = req.result
      resolve(_db)
    }
    req.onerror = () => reject(req.error)
  })
}

function tx(db: IDBDatabase, mode: IDBTransactionMode): IDBObjectStore {
  return db.transaction([STORE_QUEUE], mode).objectStore(STORE_QUEUE)
}

function wrapReq<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

/** 新しい UUID v4 (crypto.randomUUID は iOS Safari 15.4+ で利用可能、fallback あり) */
export function newClientUuid(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  // RFC4122 v4 fallback using crypto.getRandomValues (CSPRNG)
  // Math.random() は CodeQL (js/insecure-randomness) に引っかかるため使用禁止
  const buf = new Uint8Array(16)
  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
    crypto.getRandomValues(buf)
  } else {
    // 最後の保険: getRandomValues も無い極古環境 (理論上現代ブラウザでは到達しない)
    throw new Error('crypto.getRandomValues is not available')
  }
  // RFC4122 §4.4: バージョン(4) と variant(10) を埋める
  buf[6] = (buf[6] & 0x0f) | 0x40
  buf[8] = (buf[8] & 0x3f) | 0x80
  const hex = Array.from(buf, (b) => b.toString(16).padStart(2, '0')).join('')
  return (
    `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-` +
    `${hex.slice(16, 20)}-${hex.slice(20, 32)}`
  )
}

/** backoff schedule: 試行回数 → 次の遅延 (ms) */
const _BACKOFF_MS = [
  0,        // 1 回目 (即座)
  1_000,    // 2 回目: 1s
  2_000,    // 3 回目: 2s
  5_000,    // 4 回目: 5s
  15_000,   // 5 回目: 15s
  60_000,   // 6 回目: 1m
  5 * 60_000,  // 7 回目: 5m
  30 * 60_000, // 8 回目: 30m
]
const _MAX_AUTO_ATTEMPTS = _BACKOFF_MS.length

function nextDelay(attempts: number): number {
  if (attempts >= _MAX_AUTO_ATTEMPTS) return -1 // 自動再試行打ち切り
  return _BACKOFF_MS[attempts]
}

/**
 * キューに 1 件 enqueue する。即時 clientUuid を返すので呼び出し側はそれを
 * "暫定 id" として UI を進められる。
 */
export async function enqueue(
  endpoint: QueueEndpoint,
  body?: Record<string, unknown>,
  pathParams?: Record<string, string | number>,
): Promise<{ clientUuid: string; localId: number }> {
  const db = await openDb()
  const clientUuid = newClientUuid()
  const item: QueueItem = {
    clientUuid,
    endpoint,
    body,
    pathParams,
    attempts: 0,
    nextAttemptAt: Date.now(),
    manualRetry: false,
    queuedAt: Date.now(),
  }
  const store = tx(db, 'readwrite')
  const localId = (await wrapReq(store.add(item))) as IDBValidKey as number
  return { clientUuid, localId }
}

/**
 * 単一 item を送信。成功なら DB から削除、失敗なら attempts を更新して
 * 次回スケジュール時刻を仕込む。manualRetry に到達したら停止して UI 通知させる。
 */
async function trySend(item: QueueItem): Promise<'ok' | 'retry' | 'manual'> {
  // path placeholder 置換
  let url = item.endpoint.split(' ')[1] // "POST /api/rallies" → "/api/rallies"
  const method = item.endpoint.split(' ')[0]
  if (item.pathParams) {
    for (const [k, v] of Object.entries(item.pathParams)) {
      url = url.replace(`:${k}`, String(v))
    }
  }

  const token = sessionStorage.getItem('shuttlescope_token')
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Idempotency-Key': item.clientUuid,
  }
  if (token) headers.Authorization = `Bearer ${token}`

  try {
    const resp = await fetch(url, {
      method,
      headers,
      body: method === 'GET' ? undefined : JSON.stringify(item.body ?? {}),
    })
    if (resp.ok) return 'ok'
    // 4xx (= クライアント側の根本問題、リトライ意味なし) → manual に格上げ
    if (resp.status >= 400 && resp.status < 500 && resp.status !== 429) {
      item.lastStatus = resp.status
      item.lastError = (await resp.text()).slice(0, 300)
      return 'manual'
    }
    item.lastStatus = resp.status
    item.lastError = `HTTP ${resp.status}`
    return 'retry'
  } catch (e) {
    item.lastError = (e instanceof Error ? e.message : String(e)).slice(0, 300)
    return 'retry'
  }
}

let _flushing = false
let _flushTimer: number | null = null

/**
 * 待機中の item を 1 巡 flush する。完了後、次の最早 nextAttemptAt まで
 * setTimeout を再スケジュール。
 */
async function flushOnce(): Promise<void> {
  if (_flushing) return
  _flushing = true
  try {
    const db = await openDb()
    const store = tx(db, 'readonly')
    const items: QueueItem[] = await wrapReq(store.getAll())
    const now = Date.now()
    for (const it of items) {
      if (it.manualRetry) continue
      if (it.nextAttemptAt > now) continue
      const result = await trySend(it)
      if (result === 'ok') {
        const wstore = tx(db, 'readwrite')
        await wrapReq(wstore.delete(it.localId!))
      } else {
        it.attempts += 1
        it.lastAttemptAt = Date.now()
        const delay = nextDelay(it.attempts)
        if (result === 'manual' || delay < 0) {
          it.manualRetry = true
        } else {
          it.nextAttemptAt = Date.now() + delay
        }
        const wstore = tx(db, 'readwrite')
        await wrapReq(wstore.put(it))
      }
    }
  } finally {
    _flushing = false
  }
  scheduleNextFlush()
}

async function scheduleNextFlush(): Promise<void> {
  if (_flushTimer != null) {
    window.clearTimeout(_flushTimer)
    _flushTimer = null
  }
  try {
    const db = await openDb()
    const store = tx(db, 'readonly')
    const items: QueueItem[] = await wrapReq(store.getAll())
    const pending = items.filter((i) => !i.manualRetry)
    if (pending.length === 0) {
      // 何もないので 30 秒後に再ポーリング (新規 enqueue 時に明示 kick もする)
      _flushTimer = window.setTimeout(flushOnce, 30_000)
      return
    }
    const earliest = Math.min(...pending.map((i) => i.nextAttemptAt))
    const delay = Math.max(0, earliest - Date.now())
    _flushTimer = window.setTimeout(flushOnce, Math.min(delay, 30_000))
  } catch {
    _flushTimer = window.setTimeout(flushOnce, 30_000)
  }
}

/** アプリ起動時に 1 回呼ぶ。enqueue 後にもう一度呼ぶと即 flush trigger。 */
export function startBackgroundFlush(): void {
  void flushOnce()
}

/** UI 表示用ステータス */
export async function getStatus(): Promise<{
  pending: number
  manualRetry: number
  oldestQueuedAt: number | null
}> {
  try {
    const db = await openDb()
    const items: QueueItem[] = await wrapReq(tx(db, 'readonly').getAll())
    const pending = items.filter((i) => !i.manualRetry)
    const manual = items.filter((i) => i.manualRetry)
    return {
      pending: pending.length,
      manualRetry: manual.length,
      oldestQueuedAt: items.length ? Math.min(...items.map((i) => i.queuedAt)) : null,
    }
  } catch {
    return { pending: 0, manualRetry: 0, oldestQueuedAt: null }
  }
}

/** UI から「手動再送」ボタンで呼ぶ */
export async function retryAllManual(): Promise<void> {
  const db = await openDb()
  const items: QueueItem[] = await wrapReq(tx(db, 'readonly').getAll())
  const wstore = tx(db, 'readwrite')
  const now = Date.now()
  for (const it of items) {
    if (!it.manualRetry) continue
    it.manualRetry = false
    it.attempts = 0
    it.nextAttemptAt = now
    it.lastError = undefined
    it.lastStatus = undefined
    await wrapReq(wstore.put(it))
  }
  void flushOnce()
}

/** 開発・テスト用: キュー全消去 */
export async function clearAll(): Promise<void> {
  const db = await openDb()
  await wrapReq(tx(db, 'readwrite').clear())
}

/** online ↔ offline 切替時に即 flush */
if (typeof window !== 'undefined') {
  window.addEventListener('online', () => void flushOnce())
  // タブが foreground に戻った時にも flush
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') void flushOnce()
  })
}
