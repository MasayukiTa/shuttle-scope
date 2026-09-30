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
  | 'DELETE /api/rallies/:id'
  | 'POST /api/strokes?rally_id=:rally_id'
  | 'PUT /api/strokes/:id'
  | 'DELETE /api/strokes/:id'
  | 'PUT /api/rallies/:id'

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
  /**
   * 同じ論理リソース内で送信順序を守るためのキー。
   * 例: rally:42。未指定時は endpoint/pathParams から導出する。
   */
  sequenceKey?: string
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
  /**
   * この入力を作った認証ユーザー (JWT の sub)。共有端末で別ユーザーの資格情報を
   * 使って再送しないための所有者。未設定 (旧データ / 所有者を特定できなかった入力)
   * は自動再送せず、本人が「手動再送」を押した時にだけ、その時のユーザーのものになる。
   */
  ownerUserId?: number
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

/** JWT の payload から user id (sub) を取り出す。検証はサーバー側の責務で、ここは
 *  「今送ろうとしているトークンは誰のものか」を入力の所有者と突き合わせるためだけに使う。 */
export function tokenUserId(token: string | null | undefined): number | null {
  if (!token) return null
  const part = token.split('.')[1]
  if (!part) return null
  try {
    const b64 = part.replace(/-/g, '+').replace(/_/g, '/')
    const json = atob(b64.padEnd(Math.ceil(b64.length / 4) * 4, '='))
    const sub = Number((JSON.parse(json) as { sub?: unknown }).sub)
    return Number.isInteger(sub) && sub > 0 ? sub : null
  } catch {
    return null
  }
}

/** 現在ログイン中 (= 送信に使われるトークンの) ユーザー。 */
export function currentQueueOwnerId(): number | null {
  try {
    return tokenUserId(sessionStorage.getItem('shuttlescope_token'))
  } catch {
    return null
  }
}

export type QueueOwnership = 'mine' | 'foreign' | 'legacy'

/** 入力が現在のユーザーのものか。legacy = 所有者不明 (自動では誰のものにもしない)。 */
export function queueItemOwnership(
  item: Pick<QueueItem, 'ownerUserId'>,
  currentUserId: number | null,
): QueueOwnership {
  if (item.ownerUserId == null) return 'legacy'
  return currentUserId != null && item.ownerUserId === currentUserId ? 'mine' : 'foreign'
}

/**
 * flush が 1 件をどう扱うか。
 *   skip = 他のユーザーの入力。何も変えず、順序の遮断もしない
 *   hold = 所有者不明。自動では送らず、手動再送待ちにして残す
 *   send = 現在のユーザー本人の入力。送信対象
 */
export function queueFlushDecision(
  item: Pick<QueueItem, 'ownerUserId'>,
  currentUserId: number | null,
): 'skip' | 'hold' | 'send' {
  const o = queueItemOwnership(item, currentUserId)
  return o === 'foreign' ? 'skip' : o === 'legacy' ? 'hold' : 'send'
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
  options?: { sequenceKey?: string },
): Promise<{ clientUuid: string; localId: number }> {
  const db = await openDb()
  const clientUuid = newClientUuid()
  const item: QueueItem = {
    clientUuid,
    endpoint,
    body,
    pathParams,
    sequenceKey: options?.sequenceKey,
    attempts: 0,
    nextAttemptAt: Date.now(),
    manualRetry: false,
    queuedAt: Date.now(),
    // 所有者が取れない時 (セッション切れの直後など) も入力は捨てない。所有者なしで
    // 保存し、自動再送はせず本人の手動再送を待つ。
    ownerUserId: currentQueueOwnerId() ?? undefined,
  }
  const store = tx(db, 'readwrite')
  const localId = (await wrapReq(store.add(item))) as IDBValidKey as number
  return { clientUuid, localId }
}

/**
 * 単一 item を送信。成功なら DB から削除、失敗なら attempts を更新して
 * 次回スケジュール時刻を仕込む。manualRetry に到達したら停止して UI 通知させる。
 */
export type QueueSendResult = 'ok' | 'retry' | 'manual' | 'auth' | 'foreign'

export function classifyQueueHttpFailure(
  status: number,
): Exclude<QueueSendResult, 'ok' | 'foreign'> {
  if (status === 401) return 'auth'
  if (status >= 400 && status < 500 && status !== 429) return 'manual'
  return 'retry'
}

export function queueSequenceKey(
  item: Pick<QueueItem, 'endpoint' | 'pathParams' | 'sequenceKey'>,
): string | null {
  if (item.sequenceKey) return item.sequenceKey

  if (item.endpoint === 'POST /api/strokes?rally_id=:rally_id') {
    const rallyId = item.pathParams?.rally_id
    return rallyId == null ? null : `rally:${rallyId}`
  }

  if (
    item.endpoint === 'PUT /api/rallies/:id'
    || item.endpoint === 'DELETE /api/rallies/:id'
  ) {
    const rallyId = item.pathParams?.id
    return rallyId == null ? null : `rally:${rallyId}`
  }

  return null
}

/**
 * ownerUserId を渡すと、そのユーザー本人の入力だけで次回送信時刻を決める
 * (他ユーザー・所有者不明の入力は自動送信されないので、待っても無意味)。
 */
export function nextSequenceRunnableAt(
  items: QueueItem[],
  ownerUserId?: number | null,
): number | null {
  const blockedSequenceKeys = new Set<string>()
  let earliest: number | null = null

  for (const it of [...items].sort((a, b) => (a.localId ?? 0) - (b.localId ?? 0))) {
    if (ownerUserId !== undefined && queueItemOwnership(it, ownerUserId) !== 'mine') continue
    const sequenceKey = queueSequenceKey(it)
    if (sequenceKey) {
      if (blockedSequenceKeys.has(sequenceKey)) continue
      // 同一 sequence では最古の item だけが scheduling を決める。
      // manualRetry なら後続も自動送信させない。
      blockedSequenceKeys.add(sequenceKey)
    }
    if (it.manualRetry) continue
    if (earliest == null || it.nextAttemptAt < earliest) earliest = it.nextAttemptAt
  }

  return earliest
}

async function trySend(item: QueueItem): Promise<QueueSendResult> {
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
  if (!token) {
    // App startup can run the queue before login/session restoration. That is
    // not a permanent payload failure and must not consume retry budget or
    // move valuable offline annotations to manualRetry.
    item.lastStatus = 401
    item.lastError = 'authentication required'
    return 'auth'
  }
  // 送る直前に、トークンの持ち主が入力の所有者と同じかを確かめる。ここが
  // 「別ユーザーの資格情報で再送しない」ことの最終的な保証 (flush 側の判定と
  // この間にセッションが切り替わっても、この照合が止める)。
  if (queueItemOwnership(item, tokenUserId(token)) !== 'mine') return 'foreign'
  headers.Authorization = `Bearer ${token}`

  try {
    const resp = await fetch(url, {
      method,
      headers,
      body: method === 'GET' ? undefined : JSON.stringify(item.body ?? {}),
    })
    if (resp.ok) return 'ok'
    item.lastStatus = resp.status
    item.lastError = (await resp.text()).slice(0, 300) || `HTTP ${resp.status}`
    return classifyQueueHttpFailure(resp.status)
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
    items.sort((a, b) => (a.localId ?? 0) - (b.localId ?? 0))
    const now = Date.now()
    const blockedSequenceKeys = new Set<string>()
    const me = currentQueueOwnerId()

    for (const it of items) {
      const decision = queueFlushDecision(it, me)
      // 他のユーザーの入力は触らない。順序の遮断もしない (自分の入力を止めない)。
      // 本人が次にログインした時に、本人の資格情報で送られる。
      if (decision === 'skip') continue

      const sequenceKey = queueSequenceKey(it)
      if (sequenceKey && blockedSequenceKeys.has(sequenceKey)) continue

      // 所有者不明の入力は、誰のものか推測して送らない。手動再送待ちにして残す。
      if (decision === 'hold') {
        if (!it.manualRetry) {
          it.manualRetry = true
          it.lastError = 'owner unknown: retry manually to send it as the current user'
          await wrapReq(tx(db, 'readwrite').put(it))
        }
        if (sequenceKey) blockedSequenceKeys.add(sequenceKey)
        continue
      }

      // 同じ rally の後続操作は、先行操作が manual/backoff 中なら追い越させない。
      if (it.manualRetry || it.nextAttemptAt > now) {
        if (sequenceKey) blockedSequenceKeys.add(sequenceKey)
        continue
      }

      const result = await trySend(it)
      if (result === 'foreign') continue  // 送信直前にセッションが切り替わった。何も変えない
      if (result === 'ok') {
        const wstore = tx(db, 'readwrite')
        await wrapReq(wstore.delete(it.localId!))
      } else {
        it.lastAttemptAt = Date.now()
        if (result === 'auth') {
          // Authentication is an external prerequisite, not a failed send.
          // Preserve attempts and retry soon after login/session restoration.
          it.nextAttemptAt = Date.now() + 30_000
        } else {
          it.attempts += 1
          const delay = nextDelay(it.attempts)
          if (result === 'manual' || delay < 0) {
            it.manualRetry = true
          } else {
            it.nextAttemptAt = Date.now() + delay
          }
        }
        const wstore = tx(db, 'readwrite')
        await wrapReq(wstore.put(it))
        if (sequenceKey) blockedSequenceKeys.add(sequenceKey)
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
    const earliest = nextSequenceRunnableAt(items, currentQueueOwnerId())
    if (earliest == null) {
      // 何も自動送信できない (空 or manualRetry で sequence が塞がれている)。
      _flushTimer = window.setTimeout(flushOnce, 30_000)
      return
    }
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
  /** 別のユーザーの未送信 (この端末に残っている。表示・操作の対象にしない) */
  otherUsers: number
}> {
  try {
    const db = await openDb()
    const all: QueueItem[] = await wrapReq(tx(db, 'readonly').getAll())
    const me = currentQueueOwnerId()
    const items = all.filter((i) => queueItemOwnership(i, me) !== 'foreign')
    const pending = items.filter((i) => !i.manualRetry)
    const manual = items.filter((i) => i.manualRetry)
    return {
      pending: pending.length,
      manualRetry: manual.length,
      oldestQueuedAt: items.length ? Math.min(...items.map((i) => i.queuedAt)) : null,
      otherUsers: all.length - items.length,
    }
  } catch {
    return { pending: 0, manualRetry: 0, oldestQueuedAt: null, otherUsers: 0 }
  }
}

/** UI から「手動再送」ボタンで呼ぶ */
export async function retryAllManual(): Promise<void> {
  const me = currentQueueOwnerId()
  if (me == null) return  // 誰として送るか分からない間は何もしない
  const db = await openDb()
  const items: QueueItem[] = await wrapReq(tx(db, 'readonly').getAll())
  const wstore = tx(db, 'readwrite')
  const now = Date.now()
  for (const it of items) {
    if (!it.manualRetry) continue
    const ownership = queueItemOwnership(it, me)
    if (ownership === 'foreign') continue  // 他人の入力は、その人の操作でだけ再送する
    // 所有者不明の入力は、本人がこのボタンを押した時にだけ、その人のものになる。
    if (ownership === 'legacy') it.ownerUserId = me
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
