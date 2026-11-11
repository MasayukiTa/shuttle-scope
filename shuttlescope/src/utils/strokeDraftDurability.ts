/**
 * 入力中（ラリー未確定）のストロークが、セッション終了の 4 契機で失われるかを判定する純関数。
 *
 * 背景（2026-11-05 / ELN E-90e8cfaa2891 の要望）:
 *   「何か入力するたびに保存される形態であるべき。保存し終わったはずが保存失敗と出る場合がある」
 *
 * 事実（コード精読 2026-11-09）:
 *   - ラリーの確定（勝者＋終了種別）までは、サーバーには一切送られない。
 *     POST /api/strokes/batch は RallyData.winner / end_type / rally_length を必須とするため、
 *     確定前の部分ラリーはサーバーに保存できない（backend/routers/strokes.py）。
 *   - 確定前の 1 打ごとの退避は localStorage の同期書き込みのみ（saveAutosaveNow）。
 *     localStorage は容量超過・プライベートモード・無効化で書き込みが例外になり得る。
 *     これが「保存し終わったはずが保存失敗」の実体。
 *
 * 設計方針:
 *   確定前は端末（localStorage に加えて IndexedDB）へ 1 打ごとに確実に退避し、
 *   復帰後に本人の明示確定（または自動同期）でサーバーへ冪等送信する。
 *   この関数は「どの保存層に書けていれば、どの契機で失われないか」を 1 箇所で定義し、
 *   UI とテストの両方が同じ判定を参照できるようにする。
 */

/** セッションが終わる 4 つの契機（要望で挙げられたもの）。 */
export type DurabilityEvent =
  | 'closeTab'       // ラリーを確定する前にタブを閉じた
  | 'browserCrash'   // ブラウザが落ちた
  | 'networkLost'    // 通信が切れた
  | 'loggedOut'      // ログアウトされた（無操作失効・401/403 を含む）

/** 入力中ラリーが、どの保存層まで退避済みかの状態。 */
export interface DraftPersistenceState {
  /** localStorage への同期退避が成功しているか（saveAutosaveNow が成功）。 */
  localStorageSaved: boolean
  /** IndexedDB への永続退避が成功しているか（タブ／プロセスを跨いで残る）。 */
  indexedDbSaved: boolean
}

/** 1 契機ごとの判定結果。 */
export interface DurabilityVerdict {
  event: DurabilityEvent
  /** 入力済みストロークが失われるか。 */
  lost: boolean
  /** 復帰後に入力を取り戻せる保存層（空なら取り戻せない＝失われる）。 */
  recoverableFrom: Array<'localStorage' | 'indexedDB'>
  /** 判定理由（UI ツールチップ・PR 本文・監査用）。 */
  reason: string
}

/**
 * ある保存状態で、指定契機のときに入力中ストロークが失われるかを判定する。
 *
 * 不変条件:
 *   - closeTab / browserCrash / networkLost / loggedOut のいずれでも、
 *     端末（localStorage か IndexedDB のどちらか）に退避済みなら失われない。
 *   - どの層にも書けていなければ、どの契機でも失われる。
 *   - loggedOut は共有端末での情報漏れを避けるため localStorage を本人検証付きでしか
 *     復元しない。IndexedDB 側は ownerUserId で本人に紐づくため、再ログイン後に
 *     本人であれば取り戻せる。ここでは「本人が同じ端末で再開する」前提で判定する。
 */
export function classifyDraftDurability(
  event: DurabilityEvent,
  state: DraftPersistenceState,
): DurabilityVerdict {
  const recoverableFrom: Array<'localStorage' | 'indexedDB'> = []
  if (state.localStorageSaved) recoverableFrom.push('localStorage')
  if (state.indexedDbSaved) recoverableFrom.push('indexedDB')
  const lost = recoverableFrom.length === 0

  let reason: string
  if (lost) {
    reason =
      'どの保存層にも退避できていないため、確定前の入力は復帰できない'
  } else if (event === 'loggedOut') {
    reason =
      '本人が同じ端末で再ログインすれば、退避済みの入力を復元できる'
  } else {
    reason =
      '端末に退避済みのため、復帰後に入力を取り戻せる'
  }

  return { event, lost, recoverableFrom, reason }
}

/** 4 契機すべての判定をまとめて返す（PR 本文の表・UI 要約・テスト用）。 */
export function classifyAllDraftDurability(
  state: DraftPersistenceState,
): DurabilityVerdict[] {
  const events: DurabilityEvent[] = [
    'closeTab',
    'browserCrash',
    'networkLost',
    'loggedOut',
  ]
  return events.map((e) => classifyDraftDurability(e, state))
}

/**
 * 現状（この PR 以前）の保存状態: localStorage のみ、IndexedDB への入力中退避は無い。
 * localStorage の書き込みが失敗し得る（容量・プライベートモード）ので、
 * 「書けた場合」と「書けなかった場合」を分けて判定できるよう引数にする。
 */
export function legacyDraftState(localStorageSaved: boolean): DraftPersistenceState {
  return { localStorageSaved, indexedDbSaved: false }
}

/**
 * この PR 後の保存状態: 1 打ごとに localStorage と IndexedDB の両方へ退避する。
 * localStorage が失敗しても IndexedDB が残るため、入力は失われない。
 */
export function durableDraftState(
  localStorageSaved: boolean,
  indexedDbSaved: boolean,
): DraftPersistenceState {
  return { localStorageSaved, indexedDbSaved }
}
