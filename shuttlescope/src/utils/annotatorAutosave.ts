/**
 * アノテータの一時保存 (localStorage) のキーと持ち主の扱い。
 *
 * キーに user_id を入れる。入れないと、共有端末でAさんがラリー途中でログアウトしたあと、
 * 同じ試合を開いたBさんにAさんの未確定入力が復元候補として出てしまう。
 * 保存内容にも ownerUserId を持たせ、復元時に照合する (キーを書き換えられても弾く)。
 */

export const AUTOSAVE_PREFIX = 'shuttlescope.autosave.'

/** user_id が分からないとき (null) はキーを作らない = 一時保存をしない。持ち主不明の入力を残さないため。 */
export function buildAutosaveKey(
  matchId: string | number | null | undefined,
  userId: number | null | undefined,
): string | null {
  if (matchId == null || matchId === '') return null
  if (userId == null || !Number.isInteger(userId) || userId <= 0) return null
  return `${AUTOSAVE_PREFIX}${userId}.${matchId}`
}

/** 保存内容の持ち主が現在のユーザーか。持ち主の記録が無い旧形式は「違う」と扱う。 */
export function isAutosaveOwnedBy(
  saved: { ownerUserId?: number | null } | null | undefined,
  userId: number | null | undefined,
): boolean {
  if (!saved || userId == null) return false
  return saved.ownerUserId === userId
}

/** 一時保存のキーをすべて返す (旧形式 shuttlescope.autosave.{matchId} を含む)。 */
export function listAutosaveKeys(storage: Pick<Storage, 'length' | 'key'>): string[] {
  const keys: string[] = []
  for (let i = 0; i < storage.length; i++) {
    const k = storage.key(i)
    if (k && k.startsWith(AUTOSAVE_PREFIX)) keys.push(k)
  }
  return keys
}

/** ログアウト時に呼ぶ。未確定ラリーを端末に残さない。消した件数を返す。 */
export function clearAutosaveStorage(
  storage: Pick<Storage, 'length' | 'key' | 'removeItem'>,
): number {
  const keys = listAutosaveKeys(storage)
  for (const k of keys) storage.removeItem(k)
  return keys.length
}
