// fix/auth-session-persist: 認証情報を localStorage に置き、同一ブラウザの全タブで
// 共有する。以前は token / refresh / role 等を sessionStorage に置いていたため、
//   (1) 新しいタブ・ウィンドウ・ブラウザ再起動では即ログアウト
//   (2) タブ複製では 15 分後に両タブがログアウト (同じ refresh を 2 タブが使う)
//   (3) 1 タブでも refresh 応答が通信で失われると次の refresh が使い回し扱いで失効
// が起きていた。localStorage を主ストレージにして全タブで 1 つの認証世代を共有する。
//
// localStorage が使える環境では読み書きとも localStorage だけを使う。sessionStorage は
// localStorage が使えないとき (Safari private mode 等) の代替としてのみ使う。
// 以前は互換のため書きを localStorage と sessionStorage の両方に行い、読みを
// 「localStorage 優先・無ければ sessionStorage フォールバック」にしていたが、これだと
// 他タブでログアウトして localStorage が空になっても、そのタブに残った sessionStorage の
// ミラーを読んでログイン状態が残り、cross-tab logout が成立しなかった。そのため
// タブ固有の sessionStorage ミラーは残さない方針に変更した (移行時・他タブログアウト時に消す)。
// 本番では localStorage への書き込みが storage イベントで他タブへ伝播する。

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
 * 認証値を 1 つ読む。localStorage が使える環境では localStorage だけを読む
 * (sessionStorage には落ちない)。sessionStorage は localStorage が使えないとき
 * (Safari private mode 等) の代替としてのみ読む。
 *
 * 以前は localStorage に無ければ常に sessionStorage をフォールバックで読んでいたため、
 * 他タブでログアウトして localStorage の token が消えても、そのタブに残った
 * sessionStorage のミラーを拾ってログイン状態が残ってしまった (cross-tab logout 不成立)。
 */
export function getAuthItem(key: string): string | null {
  const ls = safeLocal()
  if (ls) {
    try {
      return ls.getItem(key)
    } catch {
      /* localStorage 自体が不可 → sessionStorage 代替へ */
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
 * 認証値を 1 つ書く。localStorage が使える環境では localStorage だけに書く
 * (全タブ共有・主ストレージ。書き込みは他タブで storage イベントを発火させる)。
 * sessionStorage には書かない — タブ固有の sessionStorage にミラーを残すと、
 * 他タブでのログアウト (localStorage から消える) 後もそのタブに値が残り、
 * getAuthItem がそれを拾ってログアウトが伝わらないため。
 * localStorage が使えないとき (Safari private mode 等) だけ sessionStorage を代替に使う。
 */
export function setAuthItem(key: string, value: string): void {
  const ls = safeLocal()
  if (ls) {
    try {
      ls.setItem(key, value)
      return
    } catch { /* localStorage 自体が不可 → sessionStorage 代替へ */ }
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
      const v = ss.getItem(key)
      // localStorage に既に値があるキーは上書きしない (他タブが書いた最新を尊重)。
      if (v !== null && ls.getItem(key) === null) ls.setItem(key, v)
      // 移行後は sessionStorage の認証値を消す。タブ固有のミラーを残すと、
      // 他タブのログアウトが getAuthItem のフォールバックで無効化されてしまうため。
      if (v !== null) ss.removeItem(key)
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
    // 他タブでのログアウト (token / refresh token が localStorage から消えた) の検知。
    const loggedOut =
      (e.key === TOKEN_KEY || e.key === REFRESH_KEY) && e.newValue === null
    if (loggedOut || e.key === null) {
      // 他タブでログアウトされた。このタブが未認証へ切り替わる前に、入力中のラリーを
      // 今すぐ一時保存へ書き出させる (PR 243 と同じ退避。アノテータ画面が開いていれば拾う。
      // 開いていなければ無害)。AUTOSAVE_FLUSH_EVENT の値を文字列直書きにして
      // annotatorAutosave への依存を持たない (authStorage を UI 層から疎に保つ)。
      try {
        window.dispatchEvent(new Event('shuttlescope:autosave-flush'))
      } catch {
        /* ignore */
      }
      // このタブに残っている sessionStorage の認証ミラーも消す。消さないと getAuthItem が
      // localStorage 不可時の代替として、あるいは移行前の旧値としてそれを拾い、
      // 読み込み直してもログインが続いてしまう。
      const ss = safeSession()
      if (ss) {
        for (const key of AUTH_KEYS) {
          try { ss.removeItem(key) } catch { /* ignore */ }
        }
      }
    }
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
