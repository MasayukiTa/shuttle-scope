/**
 * 記録画面の「未送信 N 件 / 保存済み / 送信失敗(再試行)」表示の状態判定 (純ロジック)。
 *
 * UI と切り離して単体テストできるよう、入力 (未送信件数・オンライン否・
 * 直近の送信が失敗したか) から表示状態を導く関数だけをここに置く。
 * useOfflineSync / AnnotatorPage がこれを呼ぶ。
 */

export type SyncState = 'saved' | 'offline' | 'failed'

export interface SyncStatusInput {
  /** 本人の未送信 (owned キュー) 件数。IndexedDB から数えた値。 */
  unsentCount: number
  /** navigator.onLine が false （通信断）か。 */
  offline: boolean
  /** 直近の送信試行が通信エラーで失敗したか（再試行で直る種類）。 */
  lastSendFailed: boolean
}

export interface SyncStatusView {
  state: SyncState
  unsentCount: number
  /** バッジを常時出すか。未送信が 0 でもオフラインなら目立つ表示を出す。 */
  prominent: boolean
}

/**
 * 表示状態を導く。
 *   - オフライン → 'offline'（目立つ色）
 *   - オンラインだが直近の送信が失敗して未送信が残る → 'failed'（再試行中・目立つ色）
 *   - それ以外 → 'saved'
 * 未送信件数は負にならないように正規化する。
 */
export function deriveSyncStatus(input: SyncStatusInput): SyncStatusView {
  const unsentCount = Math.max(0, Math.floor(Number.isFinite(input.unsentCount) ? input.unsentCount : 0))
  let state: SyncState
  if (input.offline) {
    state = 'offline'
  } else if (input.lastSendFailed && unsentCount > 0) {
    state = 'failed'
  } else {
    state = 'saved'
  }
  const prominent = state !== 'saved'
  return { state, unsentCount, prominent }
}
