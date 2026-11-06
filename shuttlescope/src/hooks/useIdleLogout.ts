import { useEffect, useRef } from 'react'

// visibilitychange is deliberately not an activity event: switching tabs back and forth
// would otherwise reset the idle clock without any user input.
const IDLE_EVENTS = ['mousedown', 'keydown', 'touchstart', 'pointerdown', 'wheel'] as const
// Media playback counts as activity so watching a long match video does not trigger idle logout.
// These fire on media elements and do not bubble, so they are attached on document in the capture phase.
// timeupdate is ignored while the tab is hidden so a video left playing in a background tab does not keep the session alive forever.
const MEDIA_ACTIVITY_EVENTS = ['play', 'playing', 'timeupdate'] as const

// 全タブで最終操作時刻 (epoch ms) を共有するための localStorage キー。
// どれか 1 つのタブで操作すれば、同じオリジンで開いている全タブの無操作タイマーが
// 一緒に延びる。これが無いと、別タブで作業していても各タブが自分のクロックだけで
// 判定するため、たとえ裏で入力し続けていても手前のタブが無操作で閉じてしまう。
export const IDLE_LAST_ACTIVITY_KEY = 'shuttlescope.idle.lastActivity'

function readSharedLastActivity(): number | null {
  try {
    const v = localStorage.getItem(IDLE_LAST_ACTIVITY_KEY)
    if (!v) return null
    const n = parseInt(v, 10)
    return Number.isFinite(n) && n > 0 ? n : null
  } catch {
    return null
  }
}

function writeSharedLastActivity(ts: number): void {
  try {
    localStorage.setItem(IDLE_LAST_ACTIVITY_KEY, String(ts))
  } catch {
    // localStorage が使えない環境 (private mode 等) ではタブローカルの判定に委ねる
  }
}

export interface UseIdleLogoutOptions {
  enabled: boolean
  /** 無操作で失効するまでの時間 (ms)。 */
  timeoutMs: number
  /** 失効時に呼ばれる。 */
  onIdle: () => void
  /**
   * 失効の warnMs 前に 1 度だけ呼ばれる (任意)。猶予の案内を出す用途。
   * 省略すると警告フェーズは無く、timeoutMs 経過で即 onIdle。
   */
  onWarn?: () => void
  /** onWarn を呼ぶ「失効までの残り時間」(ms)。onWarn 指定時のみ有効。既定 60000 (1 分)。 */
  warnMs?: number
  /**
   * 警告が出た後、操作が戻って失効が取り消されたときに 1 度呼ばれる (任意)。
   * 猶予ダイアログを閉じる用途。
   */
  onWarnCleared?: () => void
}

/**
 * 無操作での自動ログアウト。
 *
 * - 最終操作時刻を localStorage で全タブ共有する。別タブ・非表示タブでの操作でも
 *   全タブのタイマーが一緒に延びる (storage イベントで即時反映)。
 * - onWarn / warnMs を渡すと、失効の warnMs 前に onWarn を 1 度呼ぶ (猶予の案内)。
 *   猶予中に操作が戻れば onWarnCleared を呼んで取り消す。
 * - このフック自体は保存を行わない。失効時に未確定入力をどう退避するかは呼び出し側が
 *   onWarn / onIdle の中で決める (アノテータは onWarn で flush イベントを投げる)。
 */
export function useIdleLogout({
  enabled,
  timeoutMs,
  onIdle,
  onWarn,
  warnMs = 60_000,
  onWarnCleared,
}: UseIdleLogoutOptions) {
  const onIdleRef = useRef(onIdle)
  const onWarnRef = useRef(onWarn)
  const onWarnClearedRef = useRef(onWarnCleared)
  // この enabled 期間内で既に警告を出したか (多重発火防止)。
  const warnedRef = useRef(false)

  useEffect(() => {
    onIdleRef.current = onIdle
  }, [onIdle])
  useEffect(() => {
    onWarnRef.current = onWarn
  }, [onWarn])
  useEffect(() => {
    onWarnClearedRef.current = onWarnCleared
  }, [onWarnCleared])

  useEffect(() => {
    if (!enabled) return

    // 有効化された瞬間 (= ログイン直後) に活動時刻をリセットする。
    // これが無いと、ログイン画面を timeoutMs 以上開いたまま放置してからログインした
    // 直後の tick で「既に timeout 経過」と誤判定し、無操作でも即ログアウトされる
    // (ログイン直後にログイン画面へ戻る症状の一因)。
    const bootTs = Date.now()
    writeSharedLastActivity(bootTs)
    warnedRef.current = false

    const markActivity = (ts: number) => {
      writeSharedLastActivity(ts)
      // 警告が出ている最中に操作が戻ってきたら、猶予を取り消して通常に戻す。
      if (warnedRef.current) {
        warnedRef.current = false
        onWarnClearedRef.current?.()
      }
    }

    const bump = () => {
      markActivity(Date.now())
    }

    IDLE_EVENTS.forEach(ev => window.addEventListener(ev, bump, { passive: true }))

    const bumpMedia = (e: Event) => {
      if (e.type === 'timeupdate' && document.hidden) return
      markActivity(Date.now())
    }
    MEDIA_ACTIVITY_EVENTS.forEach(ev => document.addEventListener(ev, bumpMedia, { capture: true, passive: true }))

    // 別タブが操作すると localStorage の最終操作時刻が変わる。それを受けて
    // このタブの猶予警告も取り消す (別タブで作業が続いているため)。
    const onStorage = (e: StorageEvent) => {
      if (e.key !== IDLE_LAST_ACTIVITY_KEY) return
      if (warnedRef.current) {
        warnedRef.current = false
        onWarnClearedRef.current?.()
      }
    }
    window.addEventListener('storage', onStorage)

    const interval = window.setInterval(() => {
      // 共有値 (全タブ共通) を基準にする。別タブの操作もここに反映されている。
      const last = readSharedLastActivity() ?? bootTs
      const idleFor = Date.now() - last
      if (idleFor >= timeoutMs) {
        onIdleRef.current()
        return
      }
      // 失効の warnMs 前に入ったら 1 度だけ警告する。
      if (onWarnRef.current && !warnedRef.current && idleFor >= timeoutMs - warnMs) {
        warnedRef.current = true
        onWarnRef.current()
      }
    }, 30_000)

    return () => {
      IDLE_EVENTS.forEach(ev => window.removeEventListener(ev, bump))
      MEDIA_ACTIVITY_EVENTS.forEach(ev => document.removeEventListener(ev, bumpMedia, { capture: true } as EventListenerOptions))
      window.removeEventListener('storage', onStorage)
      window.clearInterval(interval)
    }
  }, [enabled, timeoutMs, warnMs])
}
