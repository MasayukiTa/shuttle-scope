/**
 * アノテータの一時保存 (localStorage) のキーと持ち主の扱い。
 *
 * キーに user_id を入れる。入れないと、共有端末でAさんがラリー途中でログアウトしたあと、
 * 同じ試合を開いたBさんにAさんの未確定入力が復元候補として出てしまう。
 * 保存内容にも ownerUserId を持たせ、復元時に照合する (キーを書き換えられても弾く)。
 */

export const AUTOSAVE_PREFIX = 'shuttlescope.autosave.'

/**
 * 「入力中のラリーを今すぐ一時保存して」と依頼する window イベント名。
 *
 * 無操作タイムアウトの警告が出た瞬間に App 側がこれを dispatch し、アノテータ画面が
 * 受け取って現在の未確定入力を localStorage へ書き出す。これにより、失効する前に必ず
 * 退避が済み、再ログイン後に復元できる。アノテータが開いていないときは誰も拾わないので
 * 無害 (no-op)。
 */
export const AUTOSAVE_FLUSH_EVENT = 'shuttlescope:autosave-flush'

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

/**
 * セッションが終る契機。それぞれで「入力中のラリーを失効前に端末へ書き出すか」と
 * 「端末の一時保存を残すか」が決まる。
 *   - closeTab / crash : タブを閉じる・ブラウザが落ちる。入力のたびに既に localStorage へ
 *     同期書き込み済みなので、ここでの追加 flush は不要。残すのも自明 (消せない)。
 *   - networkLost    : 通信が切れる。セッションは続くので端末の一時保存を触らない。
 *   - idleLogout     : 無操作失効。失効前に flush し、一時保存を残す (再ログインで復元)。
 *   - tokenExpired   : 401/403 の意図しない失効。idleLogout と同じく flush して一時保存を残す。
 *   - explicitLogout : 本人が明示的に押したログアウト。共有端末で次の利用者に残さないため消す。
 */
export type SessionEndReason =
  | 'closeTab'
  | 'crash'
  | 'networkLost'
  | 'idleLogout'
  | 'tokenExpired'
  | 'explicitLogout'

export interface SessionTeardownPlan {
  /** セッションを破棄する前に、入力中のラリーを今すぐ一時保存へ書き出すか。 */
  flushAutosaveBeforeTeardown: boolean
  /** 端末上の一時保存 (未確定ラリー) を残すか。false なら消す。 */
  keepAutosave: boolean
}

/**
 * 終了理由から、一時保存を flush するか・残すかを決める純関数。
 * App / useAuth の分岐と意味を一致させるために切り出してある。
 */
export function planSessionTeardown(reason: SessionEndReason): SessionTeardownPlan {
  switch (reason) {
    case 'idleLogout':
    case 'tokenExpired':
      // 意図しない失効。失効前に flush し、本人が再ログインで復元できるよう残す。
      return { flushAutosaveBeforeTeardown: true, keepAutosave: true }
    case 'explicitLogout':
      // 本人の意思での終了。共有端末で次の利用者に残さない。
      return { flushAutosaveBeforeTeardown: false, keepAutosave: false }
    case 'closeTab':
    case 'crash':
    case 'networkLost':
      // 入力のたびに localStorage へ同期保存済み。追加 flush は不要、一時保存は残る。
      return { flushAutosaveBeforeTeardown: false, keepAutosave: true }
  }
}
