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

/**
 * 所有者不明 (unowned) の退避。
 *
 * ユーザー ID が本当に取れない (保存値が正の整数でなく、JWT からも復元できない) 間に
 * 保存へ失敗したラリーを、失わないよう同じ ObjectStore の別枠に残す。
 *
 * 設計判断 (S-14):
 *   - 所有者を推測しない。ユーザー 0 や、後からログインした別の人の持ち物にはしない。
 *     キーは `unowned/...` で、ownerUserId を持たない。
 *   - 自動では絶対に再送しない。listPendingForMatch / countPendingForUser /
 *     useOfflineSync はこの枠を読まない (所有者付きの行だけを対象にする)。
 *   - 送るのは、ユーザーが分かった状態で本人が明示的に「自分のものとして送信」を確認
 *     した時だけ (claimUnownedForMatch)。その時点で初めて、確認した人の名前で
 *     通常の退避キューへ移る。確認しなければ、破棄 (discardUnownedForMatch) するまで
 *     この端末に残り、画面に警告が出続ける。
 *   - 端末を共有していて別の人が確認ボタンを押す危険は、モバイルの送信キュー
 *     (所有者不明は手動再送でのみ、その時のユーザーのものになる) と同じ水準の
 *     「明示操作」で受け止める。自動では誰のものにもならない、が不変条件。
 */
export type UnownedPendingRally = Omit<PendingRally, 'ownerUserId'>

const UNOWNED_PREFIX = 'unowned/'

export function unownedQueueKey(matchId: number, setId: number, rallyNum: number): string {
  return `${UNOWNED_PREFIX}${matchId}/${setId}/${rallyNum}`
}

function isUnownedRow(it: StoredPendingRally): boolean {
  return (
    typeof it.key === 'string' &&
    it.key.startsWith(UNOWNED_PREFIX) &&
    it.ownerUserId === undefined
  )
}

async function getAllRows(): Promise<StoredPendingRally[]> {
  const db = await openDb()
  try {
    return await new Promise<StoredPendingRally[]>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readonly')
      const req = tx.objectStore(STORE).getAll()
      req.onsuccess = () => resolve((req.result ?? []) as StoredPendingRally[])
      req.onerror = () => reject(req.error ?? new Error('list error'))
    })
  } finally {
    db.close()
  }
}

/** 所有者不明の枠へ退避する。書けたかどうかを返す (呼び出し側は失敗を画面に出す)。 */
export async function stashUnowned(p: UnownedPendingRally): Promise<boolean> {
  try {
    const db = await openDb()
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite')
      tx.objectStore(STORE).put({
        ...p,
        key: unownedQueueKey(p.matchId, p.setId, p.rallyNum),
      })
      tx.oncomplete = () => resolve()
      tx.onerror = () => reject(tx.error ?? new Error('stash error'))
    })
    db.close()
    return true
  } catch (err) {
    if (typeof console !== 'undefined') console.warn('[offline] unowned stash failed:', err)
    return false
  }
}

/** 送信成功後に所有者不明の退避を消す。 */
export async function removeUnowned(
  matchId: number,
  setId: number,
  rallyNum: number,
): Promise<void> {
  try {
    const db = await openDb()
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite')
      tx.objectStore(STORE).delete(unownedQueueKey(matchId, setId, rallyNum))
      tx.oncomplete = () => resolve()
      tx.onerror = () => reject(tx.error ?? new Error('remove error'))
    })
    db.close()
  } catch (err) {
    if (typeof console !== 'undefined') console.warn('[offline] unowned remove failed:', err)
  }
}

/** ある試合の所有者不明の退避。 */
export async function listUnownedForMatch(matchId: number): Promise<UnownedPendingRally[]> {
  try {
    const items = await getAllRows()
    return items
      .filter((it) => isUnownedRow(it) && Number(it.matchId) === matchId)
      .map((it) => ({
        matchId: Number(it.matchId),
        setId: Number(it.setId),
        rallyNum: Number(it.rallyNum),
        payload: it.payload,
        queued_at: String(it.queued_at ?? ''),
      }))
      .sort((a, b) => (a.queued_at < b.queued_at ? -1 : 1))
  } catch (err) {
    if (typeof console !== 'undefined') console.warn('[offline] unowned list failed:', err)
    return []
  }
}

/** 明示的な破棄。消した件数を返す。 */
export async function discardUnownedForMatch(matchId: number): Promise<number> {
  const rows = await listUnownedForMatch(matchId)
  for (const r of rows) await removeUnowned(r.matchId, r.setId, r.rallyNum)
  return rows.length
}

/**
 * 明示的な確認の後にだけ呼ぶ。所有者不明の退避を `ownerUserId` の持ち物として通常の
 * 退避キューへ移す (再送は useOfflineSync が安定キーで行う)。移せた件数を返す。
 * 所有者が正の整数でなければ何もしない (0 や NaN の持ち物を作らない)。
 */
export async function claimUnownedForMatch(
  matchId: number,
  ownerUserId: number,
): Promise<number> {
  if (!Number.isInteger(ownerUserId) || ownerUserId <= 0) return 0
  const rows = await listUnownedForMatch(matchId)
  let moved = 0
  for (const r of rows) {
    // 先に所有者付きで書き、書けた時だけ不明枠を消す (途中で落ちても失わない)。
    await stashPending({ ...r, ownerUserId })
    const still = await listPendingForMatch(matchId, ownerUserId)
    if (still.some((s) => s.setId === r.setId && s.rallyNum === r.rallyNum)) {
      await removeUnowned(r.matchId, r.setId, r.rallyNum)
      moved += 1
    }
  }
  return moved
}

/**
 * ラリー保存前の退避。所有者が分かれば本人の枠、分からなければ所有者不明の枠へ。
 * どちらの枠に入れたかを返す (保存成功時の削除に使う)。
 */
export async function stashRallyBeforeSave(
  ownerUserId: number | null,
  p: UnownedPendingRally,
): Promise<'owned' | 'unowned'> {
  if (ownerUserId != null) {
    await stashPending({ ...p, ownerUserId })
    return 'owned'
  }
  await stashUnowned(p)
  return 'unowned'
}

/** stashRallyBeforeSave の逆。送信成功を確認した後に、入れた枠から消す。 */
export async function removeRallyAfterSave(
  ownerUserId: number | null,
  matchId: number,
  setId: number,
  rallyNum: number,
): Promise<void> {
  if (ownerUserId != null) await removePending(ownerUserId, matchId, setId, rallyNum)
  else await removeUnowned(matchId, setId, rallyNum)
}
