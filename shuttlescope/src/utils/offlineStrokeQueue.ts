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
    Number.isFinite(Number(item.rallyNum)) &&
    // draft/ 行は入力中（ラリー未確定）の snapshot だけを持ち payload が無い。
    // payload 無しを送ると body 空で 422 になり保存が延々失敗する。送信対象から
    // 外し、IndexedDB には残す（確定時に AnnotatorPage が owned 枠へ payload 付きで送る）。
    item.payload !== undefined
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

/**
 * 現在のユーザー本人の未送信ラリーを、試合をまたいで全件返す。
 *
 * countPendingForUser と違い、IndexedDB の読み取りに失敗したら 0 を返さず
 * **例外を投げる**。ログアウト確認 (G4 #529) では「0 件だから黙ってログアウト」と
 * 「読めなかった」を取り違えると、未送信データを残したまま次の人に端末を渡したり、
 * 逆に本当に 0 件なのに毎回ダイアログを出したりする。呼び出し側が失敗を検知して
 * ログアウトを中断できるよう、ここでは握りつぶさない。
 */
export async function listPendingForUserStrict(
  ownerUserId: number,
): Promise<PendingRally[]> {
  const db = await openDb()
  try {
    const items = await new Promise<StoredPendingRally[]>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readonly')
      const req = tx.objectStore(STORE).getAll()
      req.onsuccess = () => resolve((req.result ?? []) as StoredPendingRally[])
      req.onerror = () => reject(req.error ?? new Error('list error'))
    })
    return items
      .filter((it): it is PendingRally =>
        Number.isInteger(it.ownerUserId) &&
        Number(it.ownerUserId) === ownerUserId &&
        Number.isFinite(Number(it.matchId)) &&
        Number.isFinite(Number(it.setId)) &&
        Number.isFinite(Number(it.rallyNum)),
      )
      .sort((a, b) => (a.queued_at < b.queued_at ? -1 : 1))
  } finally {
    db.close()
  }
}

/**
 * 本人の未送信ラリー件数。読み取りに失敗したら 0 と偽らず例外を投げる
 * (ログアウト確認で「0 件」と「読めなかった」を取り違えないため)。
 */
export async function countPendingForUserStrict(ownerUserId: number): Promise<number> {
  const items = await listPendingForUserStrict(ownerUserId)
  return items.length
}

/**
 * 本人の未送信ラリーを送信する。1 件ずつ送り、サーバが成功を返したものだけ
 * キューから消す。再送時の二重登録を防ぐため、useOfflineSync と同じ安定
 * idempotency key を使う。1 件でも送れなかったら reject し、呼び出し側が
 * 「送信に失敗した。データは残っている」と伝えられるようにする
 * (G4 #529: send に失敗したらログアウトしない、データは保持する)。
 *
 * post: 実際の送信を行う関数 (api/client の apiPost を注入する。hook の外から
 *   呼ぶため、import の循環と i18n 束縛を避けて DI にしている)。
 */
export async function flushPendingForUser(
  ownerUserId: number,
  post: (path: string, body: unknown, headers: Record<string, string>) => Promise<{ success?: boolean } | null>,
): Promise<void> {
  const items = await listPendingForUserStrict(ownerUserId)
  for (const it of items) {
    const stableKey = offlineStrokeIdempotencyKey(
      ownerUserId,
      it.matchId,
      it.setId,
      it.rallyNum,
    )
    const res = await post('/strokes/batch', it.payload, { 'X-Idempotency-Key': stableKey })
    if (!res?.success) {
      throw new Error('offline flush: send did not succeed')
    }
    await removePending(ownerUserId, it.matchId, it.setId, it.rallyNum)
  }
}

/**
 * 本人の未送信ラリーを全件削除する (G4 #529: delete は確認の後にだけ呼ぶ)。
 * 消すのは ownerUserId 本人の行だけ。所有者不明 (unowned) の行や他人の行には
 * 触れない。消した件数を返す。
 */
export async function deletePendingForUser(ownerUserId: number): Promise<number> {
  const items = await listPendingForUserStrict(ownerUserId)
  for (const it of items) {
    await removePending(ownerUserId, it.matchId, it.setId, it.rallyNum)
  }
  return items.length
}

/**
 * 入力中（ラリー未確定）の下書きを 1 打ごとに IndexedDB へ退避する。
 *
 * 背景:
 *   確定前のストロークは localStorage にしか退避されておらず、localStorage は
 *   容量超過・プライベートモード・無効化で書き込みが例外になり得た
 *   (「保存し終わったはずが保存失敗」)。IndexedDB へも二重に退避することで、
 *   タブを閉じた・クラッシュ・通信断・ログアウトのいずれでも入力が残る。
 *
 * 本キュー (owned/unowned) とは別の `draft/` prefix で保持する。確定すると
 *   AnnotatorPage が removeDraftRally で消し、確定済みラリーは通常の退避キュー
 *   (stashRallyBeforeSave) と /strokes/batch の安定冪等キーで送られる。自動再送
 *   (useOfflineSync) は draft 行を読まない — 未確定ラリーはサーバーに送れないため。
 */
export interface DraftRally {
  /** 持ち主。不明 (null) のときは退避しない (共有端末で他人に残さない)。 */
  ownerUserId: number
  matchId: number
  setId: number
  rallyNum: number
  /** 入力中スナップショット (strokes / pendingStroke / 打順 / 動画位置 等)。 */
  snapshot: unknown
  updated_at: string
}

const DRAFT_PREFIX = 'draft/'

export function draftQueueKey(
  ownerUserId: number,
  matchId: number,
  setId: number,
  rallyNum: number,
): string {
  return `${DRAFT_PREFIX}${ownerUserId}/${matchId}/${setId}/${rallyNum}`
}

/**
 * 入力中下書きを IndexedDB へ退避する。書けたかどうかを返す
 * (呼び出し側が失敗を画面に出せるように)。所有者が正の整数でなければ退避しない。
 */
export async function stashDraftRally(p: DraftRally): Promise<boolean> {
  if (!Number.isInteger(p.ownerUserId) || p.ownerUserId <= 0) return false
  try {
    const db = await openDb()
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite')
      tx.objectStore(STORE).put({
        ...p,
        key: draftQueueKey(p.ownerUserId, p.matchId, p.setId, p.rallyNum),
      })
      tx.oncomplete = () => resolve()
      tx.onerror = () => reject(tx.error ?? new Error('draft stash error'))
    })
    db.close()
    return true
  } catch (err) {
    if (typeof console !== 'undefined') console.warn('[offline] draft stash failed:', err)
    return false
  }
}

/** ラリー確定後・破棄後に入力中下書きを消す。 */
export async function removeDraftRally(
  ownerUserId: number,
  matchId: number,
  setId: number,
  rallyNum: number,
): Promise<void> {
  if (!Number.isInteger(ownerUserId) || ownerUserId <= 0) return
  try {
    const db = await openDb()
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite')
      tx.objectStore(STORE).delete(draftQueueKey(ownerUserId, matchId, setId, rallyNum))
      tx.oncomplete = () => resolve()
      tx.onerror = () => reject(tx.error ?? new Error('draft remove error'))
    })
    db.close()
  } catch (err) {
    if (typeof console !== 'undefined') console.warn('[offline] draft remove failed:', err)
  }
}

/**
 * ある試合・本人の入力中下書きを返す (復帰後の復元候補)。
 * owner 付きの draft 行だけを対象にし、他人の下書きは読まない。
 */
export async function getDraftRally(
  ownerUserId: number,
  matchId: number,
  setId: number,
  rallyNum: number,
): Promise<DraftRally | null> {
  if (!Number.isInteger(ownerUserId) || ownerUserId <= 0) return null
  try {
    const db = await openDb()
    const row = await new Promise<StoredPendingRally | undefined>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readonly')
      const req = tx.objectStore(STORE).get(
        draftQueueKey(ownerUserId, matchId, setId, rallyNum),
      )
      req.onsuccess = () => resolve(req.result as StoredPendingRally | undefined)
      req.onerror = () => reject(req.error ?? new Error('draft get error'))
    })
    db.close()
    if (!row) return null
    const r = row as unknown as Partial<DraftRally>
    if (
      Number(r.ownerUserId) !== ownerUserId ||
      Number(r.matchId) !== matchId ||
      Number(r.setId) !== setId ||
      Number(r.rallyNum) !== rallyNum
    ) {
      return null
    }
    return {
      ownerUserId,
      matchId,
      setId,
      rallyNum,
      snapshot: r.snapshot,
      updated_at: String(r.updated_at ?? ''),
    }
  } catch (err) {
    if (typeof console !== 'undefined') console.warn('[offline] draft get failed:', err)
    return null
  }
}

/**
 * 復元ダイアログが出ている間、その (match/set/rally) の自動再送を保留するレジストリ。
 *
 * 背景 (muse 実機 13:08):
 *   入力途中のラリーで「前回の未保存データを復元」ダイアログが出ている状態で
 *   通信を黄断→復帰すると、online イベント起点の自動再送が、復元/破棄が
 *   決まる前にそのラリーの owned 行を送ろうとして失敗扱いされ、「保存失敗 1 件」が
 *   出る (その後ラリーを終了すると実際には保存成功する)。
 *
 * 復元ダイアログが出ている間は、その (match/set/rally) の owned 行を再送対象から
 * 外すことで、復元か破棄が決まるまで送信を待たせる。キーは owner を含まない
 * (match/set/rally だけ) — 復元ダイアログは現在のユーザー本人の入力にしか出ないため。
 */
const heldResendKeys = new Set<string>()

function resendHoldKey(matchId: number, setId: number, rallyNum: number): string {
  return `${matchId}/${setId}/${rallyNum}`
}

/** 復元ダイアログ表示中: この (match/set/rally) の自動再送を保留する。 */
export function holdResendForRally(matchId: number, setId: number, rallyNum: number): void {
  heldResendKeys.add(resendHoldKey(matchId, setId, rallyNum))
}

/** 復元または破棄が決まった: 保留を解除する (次回の sync で送られる)。 */
export function releaseResendForRally(matchId: number, setId: number, rallyNum: number): void {
  heldResendKeys.delete(resendHoldKey(matchId, setId, rallyNum))
}

/** この (match/set/rally) の再送が保留中か。useOfflineSync の送信ループが読む。 */
export function isResendHeld(matchId: number, setId: number, rallyNum: number): boolean {
  return heldResendKeys.has(resendHoldKey(matchId, setId, rallyNum))
}
