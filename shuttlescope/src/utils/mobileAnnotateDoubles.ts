/**
 * モバイル注釈のダブルス打球者 (個人 slot) の扱い。
 *
 * backend の `Stroke.player` は player_a / partner_a / player_b / partner_b の 4 つの
 * 個人 slot で、個人別分析 (role view 等) はこの値を前提にする。モバイル Pass2/3 が
 * 打球者を A/B の 2 値へ潰すと、partner の打球が主選手へ誤帰属して後から復元できない。
 * ここに slot の列挙とチーム対応を 1 か所にまとめる。
 */
import { normalizeStrikerTeam, type Team } from '@/utils/players'

export type HitterSlot = 'player_a' | 'partner_a' | 'player_b' | 'partner_b'

const SLOTS_BY_TEAM: Record<Team, readonly [HitterSlot, HitterSlot]> = {
  player_a: ['player_a', 'partner_a'],
  player_b: ['player_b', 'partner_b'],
}

/** match.format がダブルスか (doubles_md / doubles_wd / doubles_xd / doubles)。 */
export function isDoublesFormat(format: unknown): boolean {
  return typeof format === 'string' && format.startsWith('doubles')
}

/** そのチームに属する個人 slot (主選手, パートナー)。 */
export function slotsOfTeam(team: Team): readonly [HitterSlot, HitterSlot] {
  return SLOTS_BY_TEAM[team]
}

/** slot がチームに属するか。 */
export function slotBelongsToTeam(slot: HitterSlot | null | undefined, team: Team): boolean {
  return slot != null && normalizeStrikerTeam(slot) === team
}

/**
 * 保存する打球者。シングルスはチーム値のまま、ダブルスは選ばれた slot を使う。
 * ダブルスで slot が未選択 (またはチーム違い) なら null を返し、呼び出し側は保存させない。
 */
export function resolveHitter(
  doubles: boolean,
  team: Team,
  slot: HitterSlot | null | undefined,
): HitterSlot | null {
  if (!doubles) return team
  return slotBelongsToTeam(slot, team) ? (slot as HitterSlot) : null
}
