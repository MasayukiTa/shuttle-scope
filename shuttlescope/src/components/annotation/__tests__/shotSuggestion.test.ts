/**
 * shotSuggestion の純関数テスト。
 *
 * 検証:
 * - countNextShotTransitions: 隣接ペア集計 / lastShotType=null / 一致なし
 * - sortGroupByCounts: 頻度降順 + 同数は元順 (安定ソート) / 非破壊
 * - rankShotGroups: 履歴ゼロ時は順序不変 + topSuggestion=null (後方互換) /
 *                   頻度で並べ替え / topSuggestion の決定性 /
 *                   グループに無い種別は topSuggestion にしない
 *
 * 実在の選手名・実データは一切使わない (合成ショット列のみ)。
 */
import { describe, it, expect } from 'vitest'
import type { ShotType } from '@/types'
import {
  countNextShotTransitions,
  sortGroupByCounts,
  rankShotGroups,
  type ShotGroup,
  type ShotTypeRecord,
} from '../shotSuggestion'

const rec = (s: ShotType): ShotTypeRecord => ({ shot_type: s })

describe('countNextShotTransitions', () => {
  it('直前種別の「次」の出現回数を隣接ペアで数える', () => {
    // clear の次: smash, smash, drop → smash:2, drop:1
    const strokes = [
      rec('clear'), rec('smash'),
      rec('clear'), rec('smash'),
      rec('clear'), rec('drop'),
    ]
    const counts = countNextShotTransitions(strokes, 'clear')
    expect(counts.get('smash')).toBe(2)
    expect(counts.get('drop')).toBe(1)
    expect(counts.size).toBe(2)
  })

  it('lastShotType が null なら空集計', () => {
    const strokes = [rec('clear'), rec('smash')]
    expect(countNextShotTransitions(strokes, null).size).toBe(0)
  })

  it('一致する直前種別が無ければ空集計', () => {
    const strokes = [rec('clear'), rec('smash')]
    expect(countNextShotTransitions(strokes, 'lob').size).toBe(0)
  })

  it('末尾の一致は「次」が無いので数えない', () => {
    const strokes = [rec('smash'), rec('clear')] // clear が末尾
    expect(countNextShotTransitions(strokes, 'clear').size).toBe(0)
  })
})

describe('sortGroupByCounts', () => {
  it('頻度降順に並べ、同数は元順を保つ (安定)', () => {
    const shots: ShotType[] = ['net_shot', 'smash', 'drop', 'clear']
    const counts = new Map<ShotType, number>([['drop', 3], ['net_shot', 1], ['smash', 1]])
    // drop(3) → net_shot(1) → smash(1) [元順] → clear(0)
    expect(sortGroupByCounts(shots, counts)).toEqual(['drop', 'net_shot', 'smash', 'clear'])
  })

  it('入力配列を破壊しない', () => {
    const shots: ShotType[] = ['net_shot', 'smash']
    const copy = [...shots]
    sortGroupByCounts(shots, new Map([['smash', 5]]))
    expect(shots).toEqual(copy)
  })

  it('全て count 0 なら元順のまま', () => {
    const shots: ShotType[] = ['a' as ShotType, 'b' as ShotType, 'c' as ShotType]
    expect(sortGroupByCounts(shots, new Map())).toEqual(shots)
  })
})

describe('rankShotGroups', () => {
  const groups: ShotGroup[] = [
    { labelKey: 'g.net', shots: ['net_shot', 'push_rush', 'cross_net'] },
    { labelKey: 'g.back', shots: ['smash', 'clear', 'drop'] },
  ]

  it('履歴が無ければ順序不変・topSuggestion は null (後方互換)', () => {
    const r = rankShotGroups(groups, [], 'clear')
    expect(r.groups.map((g) => g.shots)).toEqual([
      ['net_shot', 'push_rush', 'cross_net'],
      ['smash', 'clear', 'drop'],
    ])
    expect(r.topSuggestion).toBeNull()
  })

  it('lastShotType が null なら順序不変・topSuggestion は null', () => {
    const strokes = [rec('clear'), rec('smash'), rec('clear'), rec('smash')]
    const r = rankShotGroups(groups, strokes, null)
    expect(r.groups.map((g) => g.shots)).toEqual([
      ['net_shot', 'push_rush', 'cross_net'],
      ['smash', 'clear', 'drop'],
    ])
    expect(r.topSuggestion).toBeNull()
  })

  it('現ラリー履歴の頻度でグループ内を並べ替える', () => {
    // clear の次: drop, drop, smash → drop:2, smash:1
    const strokes = [
      rec('clear'), rec('drop'),
      rec('clear'), rec('drop'),
      rec('clear'), rec('smash'),
    ]
    const r = rankShotGroups(groups, strokes, 'clear')
    // back グループ: drop(2) → smash(1) → clear(0)
    expect(r.groups[1].shots).toEqual(['drop', 'smash', 'clear'])
    // net グループは全て count 0 → 元順
    expect(r.groups[0].shots).toEqual(['net_shot', 'push_rush', 'cross_net'])
    expect(r.topSuggestion).toBe('drop')
  })

  it('topSuggestion はグループに実在する種別のみ (表示外の多数派は無視)', () => {
    // clear の次に lob が最多だが、lob はどのグループにも無い → 無視。
    // グループ内実在の最多は smash。
    const strokes = [
      rec('clear'), rec('lob'),
      rec('clear'), rec('lob'),
      rec('clear'), rec('smash'),
    ]
    const r = rankShotGroups(groups, strokes, 'clear')
    expect(r.topSuggestion).toBe('smash')
  })

  it('元のグループ配列を破壊しない', () => {
    const snapshot = JSON.stringify(groups)
    const strokes = [rec('clear'), rec('drop'), rec('clear'), rec('drop')]
    rankShotGroups(groups, strokes, 'clear')
    expect(JSON.stringify(groups)).toBe(snapshot)
  })
})
