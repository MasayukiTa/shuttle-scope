/**
 * ミッドラリー (ラリー確定前) の未保存ストローク自動保存スケジューラ。
 *
 * 背景:
 *   これまでストロークは **ラリー終了時 (confirmRally) にしか** サーバーへ
 *   送られなかった (AnnotatorPage / LiveInputPage の buildBatchPayload ->
 *   /strokes/batch)。ラリーが長い・端末が落ちる・通信が切れると、確定前の入力が
 *   丸ごと失われ得る。入力途中でも、最後の入力から 5 秒経ったら、その時点までの
 *   ラリーをサーバーへ退避送信する。
 *
 * なぜ既存の /strokes/batch と安定冪等キーをそのまま使うか:
 *   - サーバーの /strokes/batch は同じ (set_id, rally_num) のラリーが既にあると
 *     **打球を足さず** already_saved の冪等応答を返す。同じ安定冪等キー
 *     offlineStrokeIdempotencyKey(owner, match, set, rally) を付けた再送は
 *     サーバー側で replay される。
 *   - したがってミッドラリー保存とラリー終了時の最終保存が同じ (set, rally) +
 *     同じキーで送られる限り、strokes は二重 INSERT されず、部分一意制約
 *     uq_strokes_rally_id_stroke_num_active (deleted_at IS NULL) に当たらない。
 *   - 送る単位は「そのラリーの現時点の全ストローク」= 既存 buildBatchPayload と
 *     同一。batch はラリー単位 (追記 API ではない) なので、増分だけを送る別経路は
 *     作らない (サーバー側スキーマ・冪等の仕組みを一切変えない)。
 *
 * 失敗時:
 *   PR 250 のローカル退避 (stashRallyBeforeSave) は消さない。次の入力 (5 秒
 *   デバウンスの張り直し) か、30 秒ごとの再試行で、同じ安定キーで送り直す。
 *   成功した分だけ removeRallyAfterSave で未保存から外す。
 *
 * UI は触らない (表示は別 job 担当)。このモジュールは純粋なスケジューラで、
 *   タイマー・送信・退避・削除をすべて DI で受け取り、React や i18n に依存しない。
 *   useOfflineSync.flushPendingForUser と同じ「post を注入する」流儀。
 */
import type { StrokeInput } from '@/types'
import { buildBatchPayload, type BatchPayload } from '@/utils/annotationPayload'
import {
  offlineStrokeIdempotencyKey,
  removeRallyAfterSave,
  stashRallyBeforeSave,
} from '@/utils/offlineStrokeQueue'

/** 最後の入力から送信までの待ち時間。連続入力は最後の入力から数える。 */
export const MID_RALLY_DEBOUNCE_MS = 5_000
/** 失敗後の再試行間隔。次の入力が無くても送り直す保険。 */
export const MID_RALLY_RETRY_MS = 30_000

/** 送信に使う最小限の POST。api/client の apiPost を注入する (DI; i18n/循環回避)。 */
export type PostFn = (
  path: string,
  body: unknown,
  headers?: Record<string, string>,
) => Promise<{ success?: boolean; data?: { rally_id?: number } } | null>

/** タイマー抽象 (テストで fake clock を注入できるようにする)。 */
export interface TimerLike {
  setTimeout: (fn: () => void, ms: number) => unknown
  clearTimeout: (handle: unknown) => void
}

const realTimer: TimerLike = {
  setTimeout: (fn, ms) => setTimeout(fn, ms),
  clearTimeout: (h) => clearTimeout(h as ReturnType<typeof setTimeout>),
}

/** 入力が起きるたびに呼び出し側が渡す、現在のラリーのスナップショット。 */
export interface MidRallySnapshot {
  ownerUserId: number | null
  matchId: number
  setId: number
  rallyNum: number
  strokes: StrokeInput[]
  winner: 'player_a' | 'player_b'
  endType: string
  scoreAAfter: number
  scoreBAfter: number
  rallyStartTimestamp: number | null
  isBasicMode: boolean
}

export interface MidRallyAutosaveDeps {
  post: PostFn
  /** 既定で realTimer。テストでは fake を注入。 */
  timer?: TimerLike
  /**
   * 送信直前にスナップショットを取り直す供給関数 (任意)。デバウンス待ちの 5 秒間に
   * さらに打球が増えることがあるため、発火時点の最新を送れるようにする。
   * 省略時は schedule / onStroke に渡された最後のスナップショットを使う。
   */
  getLatest?: () => MidRallySnapshot | null
  /** 送信成功時の通知 (任意)。保存済み rally_id を UI 以外の用途で使う場合に。 */
  onSaved?: (snap: MidRallySnapshot, rallyId: number | null) => void
  /** 送信失敗時の通知 (任意)。UI 表示は別 job が担当するのでここでは何もしないのが既定。 */
  onError?: (snap: MidRallySnapshot, err: unknown) => void
}

/**
 * 一過性 (再試行で直る) か恒久的 (何度送っても同じ) かを判定する。
 * useOfflineSync と同じ基準: 4xx は恒久 (408/429 を除く)、それ以外は一過性。
 * ミッドラリー保存では恒久的失敗でも退避は消さない (確定時の最終保存・
 * useOfflineSync に委ねる)。リトライのタイマーを張るかどうかだけを分ける。
 */
export function isTransientFailure(err: unknown): boolean {
  const status = (err as { status?: number } | null)?.status
  if (typeof status !== 'number') return true // ネットワーク断・タイムアウト等
  if (status >= 400 && status < 500) {
    return status === 408 || status === 429
  }
  return true // 5xx・その他は再試行で直り得る
}

/**
 * ミッドラリー自動保存スケジューラ。
 *
 * 使い方 (呼び出し側 = 別 job が配線する想定だが、ここでは配線しない):
 *   const s = new MidRallyAutosaver({ post: apiPost })
 *   入力のたび:   s.onStroke(snapshot)
 *   ラリー確定時: s.cancel()  // 最終保存は既存経路が同じ安定キーで送る
 */
export class MidRallyAutosaver {
  private readonly post: PostFn
  private readonly timer: TimerLike
  private readonly getLatest?: () => MidRallySnapshot | null
  private readonly onSaved?: (snap: MidRallySnapshot, rallyId: number | null) => void
  private readonly onError?: (snap: MidRallySnapshot, err: unknown) => void

  private debounceHandle: unknown = null
  private retryHandle: unknown = null
  private latest: MidRallySnapshot | null = null
  private inflight = false

  constructor(deps: MidRallyAutosaveDeps) {
    this.post = deps.post
    this.timer = deps.timer ?? realTimer
    this.getLatest = deps.getLatest
    this.onSaved = deps.onSaved
    this.onError = deps.onError
  }

  /**
   * 1 打入力されるたびに呼ぶ。最後の入力から MID_RALLY_DEBOUNCE_MS 後に送信する。
   * 連続入力ではタイマーを張り直すので、入力が止まってから 5 秒後に 1 回だけ送る。
   */
  onStroke(snap: MidRallySnapshot): void {
    this.latest = snap
    this.armDebounce()
  }

  /** onStroke と同義 (呼び出し側の意図を明示したいとき用)。 */
  schedule(snap: MidRallySnapshot): void {
    this.onStroke(snap)
  }

  private armDebounce(): void {
    if (this.debounceHandle != null) this.timer.clearTimeout(this.debounceHandle)
    this.debounceHandle = this.timer.setTimeout(() => {
      this.debounceHandle = null
      void this.flush('debounce')
    }, MID_RALLY_DEBOUNCE_MS)
  }

  private armRetry(): void {
    if (this.retryHandle != null) return // 既に再試行待ちなら二重に張らない
    this.retryHandle = this.timer.setTimeout(() => {
      this.retryHandle = null
      void this.flush('retry')
    }, MID_RALLY_RETRY_MS)
  }

  private resolveSnapshot(): MidRallySnapshot | null {
    const fresh = this.getLatest?.()
    if (fresh) {
      this.latest = fresh
      return fresh
    }
    return this.latest
  }

  /**
   * 未保存ストロークを送信する。デバウンス発火・再試行・手動の 3 経路から呼ばれる。
   * 二重送信を避けるため inflight 中は何もしない (次の契機で送る)。
   */
  async flush(_reason: 'debounce' | 'retry' | 'manual' = 'manual'): Promise<void> {
    if (this.inflight) return
    const snap = this.resolveSnapshot()
    if (!snap) return
    // 打球が 1 つも無いラリーは送らない (空ラリーの確定は既存経路が担う)。
    if (!snap.strokes || snap.strokes.length === 0) return

    this.inflight = true
    try {
      const payload: BatchPayload = buildBatchPayload({
        setId: snap.setId,
        rallyNum: snap.rallyNum,
        winner: snap.winner,
        endType: snap.endType,
        strokes: snap.strokes,
        scoreAAfter: snap.scoreAAfter,
        scoreBAfter: snap.scoreBAfter,
        rallyStartTimestamp: snap.rallyStartTimestamp,
        isBasicMode: snap.isBasicMode,
      })

      // 送信前に端末へ退避する (PR 250)。owner が取れないときは所有者不明の枠へ。
      await stashRallyBeforeSave(snap.ownerUserId, {
        matchId: snap.matchId,
        setId: snap.setId,
        rallyNum: snap.rallyNum,
        payload,
        queued_at: new Date().toISOString(),
      })

      // ラリー終了時の最終保存と **同じ** 安定冪等キー。これにより二重保存にならず
      // uq_strokes_rally_id_stroke_num_active に当たらない (同一キーは replay、
      // 同一 (set, rally) は already_saved)。owner 不明ならキー無しで送る
      // (サーバーは (set_id, rally_num) 既存チェックで二重を防ぐ)。
      const headers =
        snap.ownerUserId != null
          ? {
              'X-Idempotency-Key': offlineStrokeIdempotencyKey(
                snap.ownerUserId,
                snap.matchId,
                snap.setId,
                snap.rallyNum,
              ),
            }
          : undefined

      const res = await this.post('/strokes/batch', payload, headers)
      if (res?.success) {
        // 成功した分を未保存から外す。
        await removeRallyAfterSave(
          snap.ownerUserId,
          snap.matchId,
          snap.setId,
          snap.rallyNum,
        )
        if (this.retryHandle != null) {
          this.timer.clearTimeout(this.retryHandle)
          this.retryHandle = null
        }
        this.onSaved?.(snap, res.data?.rally_id ?? null)
      } else {
        // success=false は一過性扱い (退避は残す)。再試行を張る。
        this.armRetry()
        this.onError?.(snap, new Error('mid-rally autosave: send did not succeed'))
      }
    } catch (err) {
      // 失敗しても退避は消さない。一過性なら 30 秒後に再試行、次入力でも送り直す。
      // 恒久的失敗 (壊れたペイロード等) は確定時の最終保存 / useOfflineSync に委ね、
      // ここでは再試行タイマーを張らない (無駄な 30 秒おきの 4xx を避ける)。
      if (isTransientFailure(err)) this.armRetry()
      this.onError?.(snap, err)
    } finally {
      this.inflight = false
    }
  }

  /**
   * ラリー確定時・画面離脱時に呼ぶ。保留中のデバウンス/再試行タイマーを止める。
   * 最終保存は既存経路 (confirmRally -> /strokes/batch) が同じ安定キーで送るので、
   * ここで送信はしない (送ると二重発火になるだけで、冪等なので害は無いが無駄)。
   */
  cancel(): void {
    if (this.debounceHandle != null) {
      this.timer.clearTimeout(this.debounceHandle)
      this.debounceHandle = null
    }
    if (this.retryHandle != null) {
      this.timer.clearTimeout(this.retryHandle)
      this.retryHandle = null
    }
    this.latest = null
  }

  /** テスト・診断用: 保留中タイマーの有無。 */
  hasPending(): boolean {
    return this.debounceHandle != null || this.retryHandle != null
  }
}
