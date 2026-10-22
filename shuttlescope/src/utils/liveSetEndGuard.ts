/**
 * Live 入力でセットを確定する前の保存状態の確認 (監査 #722)。
 *
 * 最終ラリーの POST が保存中、または失敗して再送待ちのままセット終了と次セット作成へ
 * 進むと、サーバ上に「最終スコアは確定済みだがそのスコアを作ったラリーが無い」状態が残る。
 * セット終了は、保存中が 0 件・未解決の保存エラーが 0 件・端末の再送待ちが 0 件のときだけ許す。
 */
import { listPendingForMatch, listUnownedForMatch } from '@/utils/offlineStrokeQueue'

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
