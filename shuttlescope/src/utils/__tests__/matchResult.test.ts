import { describe, it, expect } from 'vitest'
import { matchOutcome, matchOutcomeLabelKey } from '../matchResult'

describe('matchOutcome', () => {
  it('win と loss はそのまま', () => {
    expect(matchOutcome('win')).toBe('win')
    expect(matchOutcome('loss')).toBe('loss')
  })

  it('未完了・不戦勝・未設定は負けにしない', () => {
    for (const r of ['unfinished', 'walkover', '', null, undefined]) {
      expect(matchOutcome(r)).toBe('unfinished')
      expect(matchOutcomeLabelKey(r)).toBe('common.unfinished_short')
    }
  })

  it('ラベルキー', () => {
    expect(matchOutcomeLabelKey('win')).toBe('common.win_short')
    expect(matchOutcomeLabelKey('loss')).toBe('common.lose_short')
  })
})
