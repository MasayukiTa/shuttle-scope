import { refreshAccessToken } from './client'

// 方針C: アクセストークンの先行リフレッシュ。
//
// アクセストークンは 15 分で失効する。失効してから 401 を受けて初めて refresh すると、
// その 1 往復のあいだ全 API が 401 を踏み、通信が不安定な回線では refresh 応答自体を
// 取りこぼして一族無効 (使い回し検出) に至る窓が開く。これを狭めるため、
//   (1) 失効の 2 分前に能動的に refresh する (REFRESH_SKEW_MS)
//   (2) タブが非表示から表示に戻ったとき (visibilitychange) に、残りが skew を
//       切っていれば即 refresh する
// を行う。refresh の実体は client.ts の single-flight な refreshAccessToken() に委ねる
// ため、複数タブ・同時多発でも refresh は 1 本にまとまる (本モジュールは発火契機だけを担う)。
//
// アクセストークン 15 分・refresh 7 日の寿命は変更しない。ここで触るのは「いつ refresh を
// 呼ぶか」だけである。

const TOKEN_KEY = 'shuttlescope_token'

/** 失効の何ミリ秒前に先行 refresh するか。15 分トークンに対し 2 分前。 */
export const REFRESH_SKEW_MS = 2 * 60_000

/** exp が壊れている / 取れないトークンに対する保守的な再試行間隔。 */
const FALLBACK_DELAY_MS = 60_000

/** タイマーの最小遅延。0 や過去になっても即時連打しないための下限。 */
const MIN_DELAY_MS = 1_000

/** JWT payload の exp (epoch 秒) を取り出す。取れなければ null。
 *  検証はサーバーの責務であり、ここは「あと何秒で失効するか」を知るためだけに読む。 */
export function tokenExpiryMs(token: string | null | undefined): number | null {
  if (!token) return null
  const part = token.split('.')[1]
  if (!part) return null
  try {
    const b64 = part.replace(/-/g, '+').replace(/_/g, '/')
    const json = atob(b64.padEnd(Math.ceil(b64.length / 4) * 4, '='))
    const exp = Number((JSON.parse(json) as { exp?: unknown }).exp)
    return Number.isFinite(exp) && exp > 0 ? exp * 1000 : null
  } catch {
    return null
  }
}

function readToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

type SchedulerHandle = {
  stop: () => void
}

let _active: SchedulerHandle | null = null

/**
 * 先行 refresh スケジューラを開始する。既に動いていれば一度停止してから貼り直す。
 * 返り値の stop() で解除できる。テスト容易性のため、timer / visibility API /
 * refresh 関数 / now は差し替え可能にしてある (既定は本番の実体)。
 */
export function startProactiveRefresh(opts: {
  getToken?: () => string | null
  refresh?: () => Promise<unknown>
  now?: () => number
  setTimer?: (cb: () => void, ms: number) => number
  clearTimer?: (id: number) => void
  addVisibilityListener?: (cb: () => void) => () => void
  isHidden?: () => boolean
} = {}): SchedulerHandle {
  const getToken = opts.getToken ?? readToken
  const refresh = opts.refresh ?? refreshAccessToken
  const now = opts.now ?? (() => Date.now())
  const setTimer =
    opts.setTimer ?? ((cb, ms) => (globalThis.setTimeout(cb, ms) as unknown as number))
  const clearTimer = opts.clearTimer ?? ((id) => globalThis.clearTimeout(id))
  const isHidden =
    opts.isHidden ??
    (() => (typeof document !== 'undefined' ? document.visibilityState === 'hidden' : false))
  const addVisibilityListener =
    opts.addVisibilityListener ??
    ((cb) => {
      if (typeof document === 'undefined') return () => {}
      document.addEventListener('visibilitychange', cb)
      return () => document.removeEventListener('visibilitychange', cb)
    })

  if (_active) {
    _active.stop()
    _active = null
  }

  let timerId: number | null = null
  let stopped = false
  let refreshing = false

  const clearPending = () => {
    if (timerId != null) {
      clearTimer(timerId)
      timerId = null
    }
  }

  const fireRefresh = () => {
    if (stopped || refreshing) return
    refreshing = true
    // refresh() を同期的に起動する (次のタイマー発火を待たせない)。
    // 返り値の promise の後処理でだけ再スケジュールする。
    let result: Promise<unknown>
    try {
      result = Promise.resolve(refresh())
    } catch {
      result = Promise.resolve()
    }
    result
      .catch(() => {
        // refresh の失敗 (transient/invalid) は client.ts 側が扱う。ここは発火契機のみ。
      })
      .finally(() => {
        refreshing = false
        // refresh 後は token が入れ替わっているので、新しい exp で貼り直す。
        schedule()
      })
  }

  function schedule(): void {
    if (stopped) return
    clearPending()
    const token = getToken()
    if (!token) {
      // 未ログイン: 何も予約しない。ログイン後に startProactiveRefresh が呼び直される。
      return
    }
    const exp = tokenExpiryMs(token)
    let delay: number
    if (exp == null) {
      delay = FALLBACK_DELAY_MS
    } else {
      const fireAt = exp - REFRESH_SKEW_MS
      delay = Math.max(MIN_DELAY_MS, fireAt - now())
    }
    timerId = setTimer(() => {
      timerId = null
      fireRefresh()
    }, delay)
  }

  const onVisibility = () => {
    if (stopped || isHidden()) return
    // タブが表示に戻った。残りが skew を切っていれば即先行 refresh、
    // そうでなければ現在の exp に合わせてタイマーを貼り直す。
    const token = getToken()
    if (!token) return
    const exp = tokenExpiryMs(token)
    if (exp != null && exp - now() <= REFRESH_SKEW_MS) {
      clearPending()
      fireRefresh()
    } else {
      schedule()
    }
  }

  const removeVisibility = addVisibilityListener(onVisibility)

  const handle: SchedulerHandle = {
    stop: () => {
      stopped = true
      clearPending()
      removeVisibility()
      if (_active === handle) _active = null
    },
  }
  _active = handle
  schedule()
  return handle
}

/** 現在動いているスケジューラを止める (ログアウト時など)。 */
export function stopProactiveRefresh(): void {
  if (_active) {
    _active.stop()
    _active = null
  }
}
