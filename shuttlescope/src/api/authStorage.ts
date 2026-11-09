// fix/auth-session-persist: 認証情報を localStorage に置き、同一ブラウザの全タブで
// 共有する。以前は token / refresh / role 等を sessionStorage に置いていたため、
//   (1) 新しいタブ・ウィンドウ・ブラウザ再起動では即ログアウト
//   (2) タブ複製では 15 分後に両タブがログアウト (同じ refresh を 2 タブが使う)
//   (3) 1 タブでも refresh 応答が通信で失われると次の refresh が使い回し扱いで失効
// が起きていた。localStorage を主ストレージにして全タブで 1 つの認証世代を共有する。
//
// 既存の多数の vitest は sessionStorage に直接 set / get して検証しているため、
// 読みは「localStorage 優先・無ければ sessionStorage フォールバック」、書きは
// 「localStorage と sessionStorage の両方」に行い、互換を保ちつつ本番では
// localStorage が storage イベントで他タブへ伝播する。

export const AUTH_CHANGED_EVENT = 'shuttlescope:auth-changed'

export const TOKEN_KEY = 'shuttlescope_token'
export const REFRESH_KEY = 'shuttlescope_refresh_token'
export const ROLE_KEY = 'shuttlescope_role'
export const PLAYER_ID_KEY = 'shuttlescope_player_id'
export const TEAM_NAME_KEY = 'shuttlescope_team_name'
export const USER_ID_KEY = 'shuttlescope_user_id'
export const DISPLAY_NAME_KEY = 'shuttlescope_display_name'
export const PAGE_ACCESS_KEY = 'shuttlescope_page_access'

/** localStorage へ移行・共有する認証関連キー一覧。storage イベント判定にも使う。 */
export const AUTH_KEYS: readonly string[] = [
  TOKEN_KEY,
  REFRESH_KEY,
  ROLE_KEY,
  PLAYER_ID_KEY,
  TEAM_NAME_KEY,
  USER_ID_KEY,
  DISPLAY_NAME_KEY,
  PAGE_ACCESS_KEY,
]

function safeLocal(): Storage | null {
  try {
    return typeof localStorage !== 'undefined' ? localStorage : null
  } catch {
    return null
  }
}

function safeSession(): Storage | null {
  try {
    return typeof sessionStorage !== 'undefined' ? sessionStorage : null
  } catch {
    return null
  }
}

/**
 * 認証値を 1 つ読む。localStorage を優先し、無ければ sessionStorage をフォールバックで読む。
 * 旧バージョン (sessionStorage のみ) で開かれたタブや、既存テストの setup との互換のため。
 */
export function getAuthItem(key: string): string | null {
  const ls = safeLocal()
  if (ls) {
    try {
      const v = ls.getItem(key)
      if (v !== null) return v
    } catch {
      /* fall through to sessionStorage */
    }
  }
  const ss = safeSession()
  if (ss) {
    try {
      return ss.getItem(key)
    } catch {
      return null
    }
  }
  return null
}

/**
 * 認証値を 1 つ書く。localStorage (全タブ共有・主) と sessionStorage (互換ミラー) の
 * 両方に書く。localStorage への書き込みは他タブで storage イベントを発火させる。
 */
export function setAuthItem(key: string, value: string): void {
  const ls = safeLocal()
  if (ls) {
    try { ls.setItem(key, value) } catch { /* ignore quota / private mode */ }
  }
  const ss = safeSession()
  if (ss) {
    try { ss.setItem(key, value) } catch { /* ignore */ }
  }
}

/** 認証値を 1 つ消す。localStorage と sessionStorage の両方から消す。 */
export function removeAuthItem(key: string): void {
  const ls = safeLocal()
  if (ls) {
    try { ls.removeItem(key) } catch { /* ignore */ }
  }
  const ss = safeSession()
  if (ss) {
    try { ss.removeItem(key) } catch { /* ignore */ }
  }
}

/**
 * 初回ロード時、sessionStorage にしか無い既存の認証値を localStorage へ移す。
 * 旧バージョンでログイン済みのタブが新バージョンに更新されたとき、ログイン状態を
 * 失わずに全タブ共有へ移行できるようにする。localStorage に既に値があるキーは
 * 上書きしない (他タブが書いた最新を尊重する)。
 */
export function migrateSessionToLocal(): void {
  const ls = safeLocal()
  const ss = safeSession()
  if (!ls || !ss) return
  for (const key of AUTH_KEYS) {
    try {
      if (ls.getItem(key) !== null) continue
      const v = ss.getItem(key)
      if (v !== null) ls.setItem(key, v)
    } catch {
      /* ignore individual key */
    }
  }
}

/**
 * 同一タブ内の listener (useAuth 等) に認証変化を知らせる。localStorage への書き込みは
 * 他タブへ storage イベントで伝わるが、書いた本人のタブには storage イベントが来ないため、
 * ここで明示的に CustomEvent を発火する。
 */
export function broadcastAuthChange(): void {
  try {
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new Event(AUTH_CHANGED_EVENT))
    }
  } catch {
    /* ignore */
  }
}

let _crossTabInstalled = false

/**
 * 他タブが localStorage の認証キーを変えたとき (ログイン・refresh・ログアウト)、
 * storage イベントを受けてこのタブの AUTH_CHANGED_EVENT を発火し、useAuth の
 * React state を再同期する。ログアウトも全タブに伝わる (他タブで token が消えると
 * ここで AUTH_CHANGED_EVENT が走り、ProtectedMainRoute が未認証を検出する)。
 * 二重登録しない。
 */
export function installCrossTabAuthSync(): void {
  if (_crossTabInstalled) return
  if (typeof window === 'undefined' || typeof window.addEventListener !== 'function') return
  _crossTabInstalled = true
  window.addEventListener('storage', (e: StorageEvent) => {
    // key === null は clear() 由来。認証キーの変化のみ React state 再同期の対象にする。
    if (e.key !== null && !AUTH_KEYS.includes(e.key)) return
    try {
      window.dispatchEvent(new Event(AUTH_CHANGED_EVENT))
    } catch {
      /* ignore */
    }
  })
}

/**
 * refresh を同一ブラウザ内で 1 本だけ走らせるためのロック。navigator.locks が使える
 * ブラウザでは排他ロック 'shuttlescope-refresh' を取り、全タブで 1 本に束ねる。
 * 非対応ブラウザ (や jsdom) ではロック無しで fn をそのまま実行し、呼び出し側
 * (client.ts) の module-level single-flight が同一タブ内の多重 refresh を 1 本にまとめる。
 */
export async function withRefreshLock<T>(fn: () => Promise<T>): Promise<T> {
  type LockManager = {
    request: (name: string, cb: () => Promise<T>) => Promise<T>
  }
  const nav =
    typeof navigator !== 'undefined'
      ? (navigator as unknown as { locks?: LockManager })
      : undefined
  const locks = nav?.locks
  if (locks && typeof locks.request === 'function') {
    try {
      return await locks.request('shuttlescope-refresh', () => fn())
    } catch {
      // ロック機構自体が失敗した場合はロック無しで実行する (refresh を止めない)。
      return fn()
    }
  }
  return fn()
}
