// 試合結果 (Match.result) の表示用分類。
// 勝敗が確定していない試合 (unfinished / walkover / 未設定) を「負」と表示しない。
export type MatchOutcome = 'win' | 'loss' | 'unfinished'

export function matchOutcome(result: string | null | undefined): MatchOutcome {
  if (result === 'win') return 'win'
  if (result === 'loss') return 'loss'
  return 'unfinished'
}

// t() に渡す i18n キー (common.win_short / lose_short / unfinished_short)
export function matchOutcomeLabelKey(result: string | null | undefined): string {
  const outcome = matchOutcome(result)
  if (outcome === 'win') return 'common.win_short'
  if (outcome === 'loss') return 'common.lose_short'
  return 'common.unfinished_short'
}
