/**
 * `stroke.player` の値を扱う。
 *
 * シングルスでは `player_a` / `player_b` の 2 値だが、ダブルスでは
 * `partner_a` / `partner_b` も入る (annotationStore は isDoubles のとき
 * `currentHitter` を書く)。そのため
 *
 *     stroke.player === 'player_a' ? A : B
 *
 * と書くと **partner_a が B として扱われる**。勝敗・サーブ権・表示名の
 * どれもチーム単位なので、比べる前にチームへ正規化する。
 * この二択を各所で書き直したのが実際の不具合だったので、ここに集約する。
 */

export type Team = 'player_a' | 'player_b'

/** `stroke.player` の所属チーム。知らない値なら undefined。 */
export function normalizeStrikerTeam(striker: string | null | undefined): Team | undefined {
  if (striker === 'player_a' || striker === 'partner_a') return 'player_a'
  if (striker === 'player_b' || striker === 'partner_b') return 'player_b'
  return undefined
}

/** 相手チーム。 */
export function opposingTeam(team: Team): Team {
  return team === 'player_a' ? 'player_b' : 'player_a'
}

/**
 * 次に打つチーム。直前の打者の相手側。
 *
 * ダブルスの partner_* を正規化せずに反転すると **同じチームに戻る**
 * (`partner_a` !== `player_a` なので `player_a` が返る)。
 */
export function nextStrikingTeam(previousStriker: string | null | undefined, fallback: Team): Team {
  const team = normalizeStrikerTeam(previousStriker)
  return team ? opposingTeam(team) : fallback
}

/** 表示用の短いチーム記号。partner も所属チームの記号になる。 */
export function teamLetter(striker: string | null | undefined): 'A' | 'B' | '?' {
  const team = normalizeStrikerTeam(striker)
  if (!team) return '?'
  return team === 'player_a' ? 'A' : 'B'
}
