/**
 * mid-rally autosave — ラリー確定前のストロークを 5 秒デバウンスでサーバーに送るユーティリティ。
 *
 * 背景:
 *   入力中 (ラリー未確定) のストロークは確定するまでサーバーに存在せず、
 *   端末クラッシュ・通信断でラリーが長いほど失うリスクが大きかった。
 *   入力から 5 秒後 (連続入力は最後の入力から 5 秒後) に、そのラリーの未保存
 *   ストロークを replace_strokes=true / final=false で送る。サーバーは既存ラリーの
 *   非削除ストロークを置き換える。ラリー終了時の最終保存は
 *   replace_strokes=true / final=true (buildBatchPayload 側)。
 *
 * 信頼性 (PR 250 / PR 260 との整合):
 *   - 送信前に端末の退避 (stashRallyBeforeSave) を残す。
 *   - 失敗したら退避を消さず、次の入力か 30 秒後に再試行する。
 *   - 成功したら退避を消し (removeRallyAfterSave)、onSent で PR 260 の未送信数から外す。
 *
 * スケジューラ本体は React に依存しない純クラス (MidRallyAutosaver) として切り出し、
 * timer / now を差し替えて単体テストできる。ページ側は useMidRallyAutosave フックで
 * 入力経路から notifyInput() を呼ぶ。
 */
import { useEffect, useRef } from 'react'

import { buildMidRallyPayload, type BuildBatchPayloadArgs, type BatchPayload } from '@/utils/annotationPayload'
import {
  stashMidRally,
  removeMidRally,
  midRallyIdempotencyKey,
  type UnownedPendingRally,
} from '@/utils/offlineStrokeQueue'

/** mid-rally 送信 1 回分の対象ラリーを組み立てるためのスナップショット。 */
export interface MidRallySnapshot {
  matchId: number
  /** buildMidRallyPayload に渡す引数 (winner / endType は確定前の暗定値でよい)。 */
  payloadArgs: BuildBatchPayloadArgs
}

export type StrokesPoster = (
  path: string,
  body: unknown,
  headers?: Record<string, string>,
) => Promise<{ success?: boolean } | null>

export interface MidRallyAutosaverDeps {
  /** 現在のラリーの未保存スナップショットを返す。送るストロークが無ければ null。 */
  getSnapshot: () => MidRallySnapshot | null
  /** キュー所有者 (userId)。不明なら null (unowned 枠へ退避)。 */
  getOwnerUserId: () => number | null
  /** 実際の送信 (api/client の apiPost を注入)。 */
  post: StrokesPoster
  /** 安定冒等キーを作る (offlineStrokeIdempotencyKey を注入)。null ならヘッダー無し。 */
  makeIdempotencyKey?: (ownerUserId: number, matchId: number, setId: number, rallyNum: number) => string
  /** 送信成功時に呼ぶ (PR 260 の未送信数再計測など)。 */
  onSent?: (snapshot: MidRallySnapshot) => void
  /** 送信失敗時に呼ぶ (退避は残したまま)。 */
  onError?: (err: unknown, snapshot: MidRallySnapshot) => void
  /** デバウンス間隔 (ms)。既定 5000。 */
  debounceMs?: number
  /** 失敗後の自動再試行間隔 (ms)。既定 30000。 */
  retryMs?: number
  /** タイマー設定 (既定 setTimeout)。テストで差し替える。 */
  setTimer?: (fn: () => void, ms: number) => ReturnType<typeof setTimeout>
  /** タイマー解除 (既定 clearTimeout)。 */
  clearTimer?: (id: ReturnType<typeof setTimeout>) => void
}

/**
 * 5 秒デバウンスの mid-rally autosave スケジューラ。React に依存しない。
 *
 * notifyInput() が呼ばれるたびにタイマーを張り直し、最後の入力から debounceMs 後に
 * flush() を走らせる。flush は getSnapshot() から現ラリーの payload を組み、退避→送信。
 * 失敗したら退避を残したまま retryMs 後に再試行をスケジュールする (次の notifyInput でも
 * 再試行される)。
 */
export class MidRallyAutosaver {
  private readonly debounceMs: number
  private readonly retryMs: number
  private readonly setTimer: (fn: () => void, ms: number) => ReturnType<typeof setTimeout>
  private readonly clearTimer: (id: ReturnType<typeof setTimeout>) => void
  private timer: ReturnType<typeof setTimeout> | null = null
  private inFlight = false
  private disposed = false
  // 確定 (ラリー保存) の stash/送信が始まったら true。以後の mid-rally flush を
  // 無効化し、飛行中だった flush の成功後処理 (mid 枠削除) も抑止する。確定ラリーの
  // 退避・送信と mid-rally autosave が競合して確定内容を上書きするのを防ぐ。
  private suspended = false

  constructor(private readonly deps: MidRallyAutosaverDeps) {
    this.debounceMs = deps.debounceMs ?? 5000
    this.retryMs = deps.retryMs ?? 30000
    this.setTimer = deps.setTimer ?? ((fn, ms) => setTimeout(fn, ms))
    this.clearTimer = deps.clearTimer ?? ((id) => clearTimeout(id))
  }

  /** 入力があるたびに呼ぶ。最後の入力から debounceMs 後に送信する。 */
  notifyInput(): void {
    if (this.disposed) return
    this.schedule(this.debounceMs)
  }

  private schedule(ms: number): void {
    if (this.timer != null) this.clearTimer(this.timer)
    this.timer = this.setTimer(() => {
      this.timer = null
      void this.flush()
    }, ms)
  }

  /** タイマー発火時または明示呼び出しで、現ラリーの未保存ストロークを送る。 */
  async flush(): Promise<void> {
    if (this.disposed || this.suspended || this.inFlight) return
    const snapshot = this.deps.getSnapshot()
    if (!snapshot) return
    const { matchId, payloadArgs } = snapshot
    // 送るストロークが無ければ何もしない。
    if (!payloadArgs.strokes || payloadArgs.strokes.length === 0) return

    const payload: BatchPayload = buildMidRallyPayload(payloadArgs)
    const ownerUserId = this.deps.getOwnerUserId()
    const setId = payloadArgs.setId
    const rallyNum = payloadArgs.rallyNum

    this.inFlight = true
    // PR 250: 送信前に端末へ退避を残す。
    const pending: UnownedPendingRally = {
      matchId,
      setId,
      rallyNum,
      payload,
      queued_at: new Date().toISOString(),
    }
    // 確定が割り込んできたら中間保存はやめる (退避も送信もしない)。
    if (this.suspended) {
      this.inFlight = false
      return
    }
    try {
      // mid-rally は確定 owned 枠とは別 prefix (mid/) に退避する。確定ラリーの
      // 退避行を中間 payload で上書きしない。
      await stashMidRally(ownerUserId, pending)
    } catch {
      /* 退避自体の失敗は握りつぶさず送信は試みる (本送避キューと同様) */
    }

    // mid-rally は確定とは別の冪等キー (offline-mid-...) を使い、中間保存の応答が
    // 確定ラリーの冪等キー (offline-...) を先取りしないようにする。テストで差し替え
    // 可能なよう makeIdempotencyKey があればそれを優先する。
    const headers =
      ownerUserId != null
        ? {
            'X-Idempotency-Key': this.deps.makeIdempotencyKey
              ? this.deps.makeIdempotencyKey(ownerUserId, matchId, setId, rallyNum)
              : midRallyIdempotencyKey(ownerUserId, matchId, setId, rallyNum),
          }
        : undefined

    try {
      const res = await this.deps.post('/strokes/batch', payload, headers)
      if (!res?.success) {
        throw new Error('mid-rally autosave: send did not succeed')
      }
      // 成功: mid 枠の退避だけを消す。確定が割り込んでいたら mid 枠も触らず、
      // 削除は確定経路に委ねる (確定 owned 行は別 prefix なので元々消えない)。
      if (!this.suspended) {
        await removeMidRally(ownerUserId, matchId, setId, rallyNum)
      }
      this.inFlight = false
      if (!this.disposed && !this.suspended) this.deps.onSent?.(snapshot)
    } catch (err) {
      // 失敗: 退避は残したまま。retryMs 後に再試行 (次の notifyInput でも再試行される)。
      this.inFlight = false
      if (!this.disposed) {
        this.deps.onError?.(err, snapshot)
        this.schedule(this.retryMs)
      }
    }
  }

  /**
   * 確定 (ラリー保存) の stash/送信が始まったことを知らせる。以後の mid-rally flush を
   * 無効化し、飛行中だった flush の成功後処理 (mid 枠削除・onSent) も抑止する。
   * ページ側は確定保存を呼ぶ直前にこれを呼ぶ。タイマーも止める。
   */
  suspend(): void {
    this.suspended = true
    this.cancel()
  }

  /** タイマーを止める (ラリー確定時など、mid-rally 送信を不要にしたいとき)。 */
  cancel(): void {
    if (this.timer != null) {
      this.clearTimer(this.timer)
      this.timer = null
    }
  }

  /** アンマウント。以後のタイマー発火・コールバックを全て無効にする。 */
  dispose(): void {
    this.disposed = true
    this.cancel()
  }
}

export interface UseMidRallyAutosaveDeps extends MidRallyAutosaverDeps {
  /**
   * 入力の合図。この値が変わるたび notifyInput() が呼ばれる (ストローク数など)。
   * ページ側は store.currentStrokes.length を渡すだけでよい。
   */
  inputSignal: number
  /** mid-rally autosave を有効にするか (ラリーアクティブかつ 1 本以上)。 */
  enabled: boolean
}

/**
 * ページから入力経路に mid-rally autosave を結線するフック。
 *
 * AnnotatorPage / LiveInputPage はこれを 1 回呼ぶだけでよい。inputSignal (ストローク数)
 * が増えるたびに notifyInput() が走り、最後の入力から 5 秒後に送信される。
 * enabled が false になったら (ラリー終了など) タイマーを止める。
 */
export function useMidRallyAutosave(deps: UseMidRallyAutosaveDeps): void {
  const { inputSignal, enabled, ...saverDeps } = deps
  // コールバック類は render ごとに変わりうるので ref に入れ、saver からは ref 経由で読む。
  const depsRef = useRef(saverDeps)
  depsRef.current = saverDeps

  const saverRef = useRef<MidRallyAutosaver | null>(null)
  if (saverRef.current == null) {
    saverRef.current = new MidRallyAutosaver({
      getSnapshot: () => depsRef.current.getSnapshot(),
      getOwnerUserId: () => depsRef.current.getOwnerUserId(),
      post: (path, body, headers) => depsRef.current.post(path, body, headers),
      makeIdempotencyKey: depsRef.current.makeIdempotencyKey
        ? (o, m, s, r) => depsRef.current.makeIdempotencyKey!(o, m, s, r)
        : undefined,
      onSent: (snap) => depsRef.current.onSent?.(snap),
      onError: (err, snap) => depsRef.current.onError?.(err, snap),
      debounceMs: saverDeps.debounceMs,
      retryMs: saverDeps.retryMs,
      setTimer: saverDeps.setTimer,
      clearTimer: saverDeps.clearTimer,
    })
  }

  // アンマウント時にタイマーを破棄。
  useEffect(() => {
    const saver = saverRef.current
    return () => { saver?.dispose() }
  }, [])

  // 入力の合図が変わるたび notifyInput。enabled=false ならタイマーを止める。
  useEffect(() => {
    const saver = saverRef.current
    if (!saver) return
    if (!enabled) {
      saver.cancel()
      return
    }
    saver.notifyInput()
  }, [inputSignal, enabled])
}
