/**
 * オフライン耐性: 未送信ラリー (strokes batch) を IndexedDB に stash する。
 *
 * Phase A 実装 (hybrid_ui_implementation_plan_v2.md §6.6 参照)。
 *
 * 設計:
 *   - DB:    'shuttlescope_offline'
 *   - store: 'pending_rallies'
 *   - key:   `${matchId}/${setId}/${rallyNum}` (string)
 *   - value: { matchId, setId, rallyNum, payload, queued_at }
 *
 * 体育館の WiFi 不安定で `/strokes/batch` 送信失敗しても 1 ラリー全消失を防ぐ。
 * 起動時 + ネットワーク復帰時に useOfflineSync が再送する。
 */

const DB_NAME = 'shuttlescope_offline'
const STORE = 'pending_rallies'
const DB_VERSION = 1

export interface PendingRally {
  matchId: number
  setId: number
  rallyNum: number
  /** /strokes/batch に送る body そのまま */
  payload: unknown
  queued_at: string  // ISO timestamp
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === 'undefined') {
      reject(new Error('IndexedDB unavailable'))
      return
    }
    const req = indexedDB.open(DB_NAME, DB_VERSION)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE, { keyPath: 'key' })
      }
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error ?? new Error('IndexedDB open error'))
  })
}

function makeKey(matchId: number, setId: number, rallyNum: number): string {
  return `${matchId}/${setId}/${rallyNum}`
}

/** ストロークバッチを stash する。送信成功後は removePending を呼ぶ。 */
export async function stashPending(p: PendingRally): Promise<void> {
  try {
    const db = await openDb()
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite')
      tx.objectStore(STORE).put({ key: makeKey(p.matchId, p.setId, p.rallyNum), ...p })
      tx.oncomplete = () => resolve()
      tx.onerror = () => reject(tx.error ?? new Error('stash error'))
    })
    db.close()
  } catch (err) {
    // IndexedDB 不可環境では stash 失敗を握りつぶす (オフライン耐性は best-effort)
    if (typeof console !== 'undefined') console.warn('[offline] stash failed:', err)
  }
}

/** 送信成功時に該当 stash を削除する。 */
export async function removePending(
  matchId: number,
  setId: number,
  rallyNum: number,
): Promise<void> {
  try {
    const db = await openDb()
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite')
      tx.objectStore(STORE).delete(makeKey(matchId, setId, rallyNum))
      tx.oncomplete = () => resolve()
      tx.onerror = () => reject(tx.error ?? new Error('remove error'))
    })
    db.close()
  } catch (err) {
    if (typeof console !== 'undefined') console.warn('[offline] remove failed:', err)
  }
}

/** 試合 ID で未送信 stash を全件取得 (古い順)。 */
export async function listPendingForMatch(matchId: number): Promise<PendingRally[]> {
  try {
    const db = await openDb()
    const items = await new Promise<PendingRally[]>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readonly')
      const req = tx.objectStore(STORE).getAll()
      req.onsuccess = () => resolve((req.result ?? []) as PendingRally[])
      req.onerror = () => reject(req.error ?? new Error('list error'))
    })
    db.close()
    return items
      .filter((it) => it.matchId === matchId)
      .sort((a, b) => (a.queued_at < b.queued_at ? -1 : 1))
  } catch (err) {
    if (typeof console !== 'undefined') console.warn('[offline] list failed:', err)
    return []
  }
}

/** 全試合の stash 件数を返す (UI バッジ用)。 */
export async function countAllPending(): Promise<number> {
  try {
    const db = await openDb()
    const n = await new Promise<number>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readonly')
      const req = tx.objectStore(STORE).count()
      req.onsuccess = () => resolve(req.result)
      req.onerror = () => reject(req.error ?? new Error('count error'))
    })
    db.close()
    return n
  } catch {
    return 0
  }
}
