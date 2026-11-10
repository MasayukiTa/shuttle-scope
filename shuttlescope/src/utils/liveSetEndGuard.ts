/**
 * Live 入力でセットを確定する前の保存状態の確認 (監査 #722)。
 *
 * 最終ラリーの POST が保存中、または失敗して再送待ちのままセット終了と次セット作成へ
 * 進むと、サーバ上に「最終スコアは確定済みだがそのスコアを作ったラリーが無い」状態が残る。
 * セット終了は、保存中が 0 件・未解決の保存エラーが 0 件・端末の再送待ちが 0 件のときだけ許す。
 */
import { listPendingForMatch, listUnownedForMatch } from '@/utils/offlineStrokeQueue'
import { isTransientSaveError } from '@/utils/errors'

export interface SetEndSaveState {
  /** 送信中のラリー数 (store.pendingSaveCount)。 */
  pendingSaveCount: number
  /** 失敗して未確認の保存エラー数 (store.saveErrors.length)。 */
  saveErrorCount: number
  /** このセットで端末に退避されたまま未送信のラリー数。 */
  queuedForSet: number
}

/** セット終了を止めるべきなら true。 */
export function isSetEndBlockedBySave(s: SetEndSaveState): boolean {
  return s.pendingSaveCount > 0 || s.saveErrorCount > 0 || s.queuedForSet > 0
}

/** 退避行のうち、指定セットのものの件数。 */
export function countQueuedForSet(rows: ReadonlyArray<{ setId: number }>, setId: number): number {
  let n = 0
  for (const r of rows) if (r.setId === setId) n += 1
  return n
}

/**
 * ラリー確定 (POST /strokes/batch) が失敗したときに、その失敗を UI 上でどう扱うかを決める。
 *
 * 要望2 (保存し終わったはずが「保存失敗」と出る) の是正:
 *   送信前に端末 (IndexedDB) へ退避し、安定した冪等キーで送っている。サーバが受理して
 *   DB に書き込んだ後、その応答が端末へ届く前にタイムアウトや通信断が起きると、呼び出し側は
 *   失敗として扱うが、実際にはサーバ側は保存済みのことがある。退避は残っており
 *   useOfflineSync が同じ冪等キーで再送するため二重にはならず最終的に整合する。この状態を
 *   「保存失敗」と赤く断定すると、保存できているのに失敗と誤って伝えることになる。
 *
 *   - 一過性 (isTransientSaveError が true: タイムアウト・通信断・5xx・408・429):
 *     「再送待ち」として扱う。保存エラー一覧には積まず (pushSaveError=false)、赤い保存失敗
 *     表示も出さない (saveFailed=false)。pendingResend=true で「自動で再送します」と伝える。
 *   - 恒久的 (その他の 4xx): 冪等キーで送り直しても直らない本当の失敗。保存エラー一覧に積み
 *     (pushSaveError=true)、保存失敗として表示する (saveFailed=true)。
 *
 * 境界は errors.ts の isTransientSaveError に一元化してあり、useOfflineSync の再送判定
 * (再試行で直るものだけ中断し、直らない 4xx は別扱い) とも一致する。
 */
export interface ConfirmSaveFailureDecision {
  /** 保存エラー一覧 (store.saveErrors) に積むか。恒久的な失敗のときだけ true。 */
  pushSaveError: boolean
  /** 恒久的な保存失敗として赤く表示するか。 */
  saveFailed: boolean
  /** 一過性で自動再送に委ねる「再送待ち」か。saveFailed とは排他。 */
  pendingResend: boolean
}

export function classifyConfirmSaveFailure(e: unknown): ConfirmSaveFailureDecision {
  if (isTransientSaveError(e)) {
    return { pushSaveError: false, saveFailed: false, pendingResend: true }
  }
  return { pushSaveError: true, saveFailed: true, pendingResend: false }
}

/** 端末の退避キューから、指定セットの未送信ラリー数を読む。所有者不明の枠も数える。 */
export async function loadQueuedRallyCount(
  ownerUserId: number | null,
  matchId: number,
  setId: number,
): Promise<number> {
  const rows =
    ownerUserId != null
      ? await listPendingForMatch(matchId, ownerUserId)
      : await listUnownedForMatch(matchId)
  return countQueuedForSet(rows, setId)
}
