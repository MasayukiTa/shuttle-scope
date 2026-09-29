/**
 * バドミントン公式ルール (BWF 21-point rally scoring) の共通判定ロジック。
 *
 * PC AnnotatorPage と Mobile MobileAnnotatePage の両方でこれを参照することで、
 * セット終了 / マッチ終了 / デュース / サーブ位置 などの判定が device 間で
 * 一致する。
 *
 * 重要: バックエンドはまだ強制しない (score_a/b は 0..1000)。ここの client-side
 * 判定は **入力支援とガード** であり、最終真実はサーバ側 rally データそのもの。
 */

export interface SetScore {
  scoreA: number
  scoreB: number
}

/** 21 点制 + デュース (20-20 で +2 リード) + 29-29 で 30 点先取 */
export const POINT_TARGET = 21
export const DEUCE_THRESHOLD = 20
export const GOLDEN_POINT = 30
/** 11 点でブレイク (最終ゲームのみコートチェンジ) */
export const SIDE_CHANGE_FINAL = 11

export type SetWinner = 'A' | 'B' | null

/**
 * セット勝者判定。null = まだ進行中。
 * - 21 点先取 + 2 点差
 * - 20-20 でデュース、+2 点差で勝ち
 * - 29-29 になったら 30 点先取の goldenpoint
 */
export function setWinner({ scoreA, scoreB }: SetScore): SetWinner {
  const hi = Math.max(scoreA, scoreB)
  const lo = Math.min(scoreA, scoreB)
  if (hi >= GOLDEN_POINT) return scoreA >= GOLDEN_POINT ? 'A' : 'B'
  if (hi >= POINT_TARGET && hi - lo >= 2) return scoreA > scoreB ? 'A' : 'B'
  return null
}

export function isDeuce({ scoreA, scoreB }: SetScore): boolean {
  return scoreA >= DEUCE_THRESHOLD && scoreB >= DEUCE_THRESHOLD &&
         Math.max(scoreA, scoreB) < GOLDEN_POINT
}

export function isGoldenPoint({ scoreA, scoreB }: SetScore): boolean {
  return scoreA === GOLDEN_POINT - 1 && scoreB === GOLDEN_POINT - 1
}

/** 「もう少しで終わる」ヒント表示用。21 点超 + 1 点差等の "あと 1 点" 状況 */
export function isSetPoint({ scoreA, scoreB }: SetScore): SetWinner {
  // 通常: 20 点で setPoint (1 点先取で勝ち = 21-19 以下)
  if (scoreA >= POINT_TARGET - 1 && scoreA - scoreB >= 1 && scoreA < GOLDEN_POINT - 1) return 'A'
  if (scoreB >= POINT_TARGET - 1 && scoreB - scoreA >= 1 && scoreB < GOLDEN_POINT - 1) return 'B'
  // デュース中: 1 点リードで setPoint
  if (isDeuce({ scoreA, scoreB })) {
    if (scoreA - scoreB === 1) return 'A'
    if (scoreB - scoreA === 1) return 'B'
  }
  // 29-x or x-29: 30 点先取で勝ち
  if (scoreA === GOLDEN_POINT - 1) return 'A'
  if (scoreB === GOLDEN_POINT - 1) return 'B'
  return null
}

export interface MatchProgress {
  /** これまでに終了した各セットの勝者。length = 終了セット数 */
  completedSetWinners: Array<'A' | 'B'>
  /** Best-of-N。3 or 5。デフォルト 3 */
  bestOf?: number
}

export type MatchWinner = 'A' | 'B' | null

/** マッチ勝者判定。 best-of-3 なら 2 セット先取、best-of-5 なら 3 セット先取 */
export function matchWinner({ completedSetWinners, bestOf = 3 }: MatchProgress): MatchWinner {
  const needed = Math.floor(bestOf / 2) + 1  // 3→2, 5→3
  const a = completedSetWinners.filter((w) => w === 'A').length
  const b = completedSetWinners.filter((w) => w === 'B').length
  if (a >= needed) return 'A'
  if (b >= needed) return 'B'
  return null
}

/**
 * サーブ位置 (right / left service court) 判定。
 *
 * BWF ラリーポイント制:
 * - サーブ側の現在スコアが **偶数** なら右サービスコート
 * - **奇数** なら左サービスコート
 *
 * server = 'A' | 'B' を渡し、その時点のセット内スコアから判定。
 */
export function serveSide(server: 'A' | 'B', score: SetScore): 'right' | 'left' {
  const s = server === 'A' ? score.scoreA : score.scoreB
  return s % 2 === 0 ? 'right' : 'left'
}

/**
 * 最終ゲーム (best-of-3 の第3、best-of-5 の第5) でどちらかが 11 点先取
 * したらコートチェンジ発生。
 */
export function isFinalSetMidChange(
  setNum: number,
  bestOf: number,
  { scoreA, scoreB }: SetScore,
): boolean {
  if (setNum !== bestOf) return false
  return Math.max(scoreA, scoreB) >= SIDE_CHANGE_FINAL
}

/**
 * 11 点ブレイク (どのセットでも 11 点に到達した時点で短い休憩)。
 * UI ヒント用。
 */
export function isMidGameBreak({ scoreA, scoreB }: SetScore): boolean {
  return Math.max(scoreA, scoreB) === SIDE_CHANGE_FINAL
}
