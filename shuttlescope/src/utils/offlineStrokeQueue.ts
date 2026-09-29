/**
 * Offline annotation durability queue for /strokes/batch.
 *
 * Security invariant:
 *   A queued payload belongs to the authenticated user who created it.
 *   It must never be replayed under a different user's credentials on a
 *   shared browser/device.
 *
 * Legacy records without ownerUserId are intentionally not auto-claimed.
 * They remain in IndexedDB for manual recovery, but automatic replay fails
 * closed instead of guessing ownership.
 */

const DB_NAME = 'shuttlescope_offline'
const STORE = 'pending_rallies'
const DB_VERSION = 1

export interface PendingRally {
  ownerUserId: number
  matchId: number
  setId: number
  rallyNum: number
  /** /strokes/batch request body. */
  payload: unknown
  queued_at: string
}

interface StoredPendingRally extends Partial<PendingRally> {
  key?: string
}

export function offlineStrokeQueueKey(
  ownerUserId: number,
  matchId: number,
  setId: number,
  rallyNum: number,
): string {
  return `${ownerUserId}/${matchId}/${setId}/${rallyNum}`
}

export function offlineStrokeIdempotencyKey(
  ownerUserId: number,
  matchId: number,
  setId: number,
  rallyNum: number,
): string {
  return `offline-${ownerUserId}-${matchId}-${setId}-${rallyNum}`
}

export function pendingRallyBelongsTo(
  item: StoredPendingRally,
  ownerUserId: number,
  matchId: number,
): item is PendingRally {
  return (
    Number.isInteger(item.ownerUserId) &&
    Number(item.ownerUserId) === ownerUserId &&
    Number(item.matchId) === matchId &&
    Number.isFinite(Number(item.setId)) &&
    Number.isFinite(Number(item.rallyNum))
  )
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

/** Persist before network send. */
export async function stashPending(p: PendingRally): Promise<void> {
  try {
    const db = await openDb()
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite')
      tx.objectStore(STORE).put({
        key: offlineStrokeQueueKey(p.ownerUserId, p.matchId, p.setId, p.rallyNum),
        ...p,
      })
      tx.oncomplete = () => resolve()
      tx.onerror = () => reject(tx.error ?? new Error('stash error'))
    })
    db.close()
  } catch (err) {
    if (typeof console !== 'undefined') console.warn('[offline] stash failed:', err)
  }
}

/** Remove only the current user's queued copy after a confirmed send. */
export async function removePending(
  ownerUserId: number,
  matchId: number,
  setId: number,
  rallyNum: number,
): Promise<void> {
  try {
    const db = await openDb()
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite')
      tx.objectStore(STORE).delete(
        offlineStrokeQueueKey(ownerUserId, matchId, setId, rallyNum),
      )
      tx.oncomplete = () => resolve()
      tx.onerror = () => reject(tx.error ?? new Error('remove error'))
    })
    db.close()
  } catch (err) {
    if (typeof console !== 'undefined') console.warn('[offline] remove failed:', err)
  }
}

/**
 * Return only queued rows owned by the current authenticated user.
 *
 * Ownerless v1 rows are deliberately excluded: assigning them to whoever
 * happens to be logged in now would recreate the cross-account replay bug.
 */
export async function listPendingForMatch(
  matchId: number,
  ownerUserId: number,
): Promise<PendingRally[]> {
  try {
    const db = await openDb()
    const items = await new Promise<StoredPendingRally[]>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readonly')
      const req = tx.objectStore(STORE).getAll()
      req.onsuccess = () => resolve((req.result ?? []) as StoredPendingRally[])
      req.onerror = () => reject(req.error ?? new Error('list error'))
    })
    db.close()
    return items
      .filter((it): it is PendingRally => pendingRallyBelongsTo(it, ownerUserId, matchId))
      .sort((a, b) => (a.queued_at < b.queued_at ? -1 : 1))
  } catch (err) {
    if (typeof console !== 'undefined') console.warn('[offline] list failed:', err)
    return []
  }
}

/** Count only the current user's queued rows. */
export async function countPendingForUser(ownerUserId: number): Promise<number> {
  try {
    const db = await openDb()
    const items = await new Promise<StoredPendingRally[]>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readonly')
      const req = tx.objectStore(STORE).getAll()
      req.onsuccess = () => resolve((req.result ?? []) as StoredPendingRally[])
      req.onerror = () => reject(req.error ?? new Error('list error'))
    })
    db.close()
    return items.filter((it) => Number(it.ownerUserId) === ownerUserId).length
  } catch {
    return 0
  }
}
