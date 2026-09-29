/**
 * コートチェンジと「どちらの半面を押させるか」の規則。
 *
 * AnnotatorPage の JSX の中に埋まっていたためテストが書けず、
 * A-1 (セット2以降、着地点として打者自身の半面を押させていた) が
 * 見た目では気づけないまま残っていた。純関数に出してテストで固定する。
 *
 * 画面の上下と選手の対応は `computePlayerASide` だけが決める。
 * 着地点の半面は **打者の反対側** であって、打者の役割 (a / b) では決まらない。
 */

export type CourtSide = 'top' | 'bottom'

function opposite(side: CourtSide): CourtSide {
  return side === 'top' ? 'bottom' : 'top'
}

/**
 * player_a が画面のどちら側に居るかを返す。
 *
 * BWF ルール: セット開始ごとにサイドチェンジ、第3セットは 11 点でサイドチェンジ。
 * setNum=1 → 0 回、setNum=2 → 1 回、setNum=3 → 2 回 (+11 点で更に 1 回)。
 */
export function computePlayerASide(
  initial: CourtSide,
  setNum: number,
  scoreA: number,
  scoreB: number,
): CourtSide {
  const betweenSets = setNum - 1
  const midSet = setNum === 3 && Math.max(scoreA, scoreB) >= 11 ? 1 : 0
  const flipped = (betweenSets + midSet) % 2 === 1
  return flipped ? opposite(initial) : initial
}

/** 打者が画面のどちら側に居るか。 */
export function hitterSide(aSide: CourtSide, currentPlayer: 'player_a' | 'player_b'): CourtSide {
  return currentPlayer === 'player_a' ? aSide : opposite(aSide)
}

/**
 * 着地点として押させる半面。打者の反対側。
 *
 * CourtDiagram の `mode` は活性にする半面も兼ねており、
 * 'land' が上半面、'hit' が下半面に対応する。
 */
export function landingSide(aSide: CourtSide, currentPlayer: 'player_a' | 'player_b'): CourtSide {
  return opposite(hitterSide(aSide, currentPlayer))
}

/** 着地点選択時に CourtDiagram へ渡す mode。 */
export function landingCourtMode(
  aSide: CourtSide,
  currentPlayer: 'player_a' | 'player_b',
): 'land' | 'hit' {
  return landingSide(aSide, currentPlayer) === 'top' ? 'land' : 'hit'
}
