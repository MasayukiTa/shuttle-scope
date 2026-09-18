/**
 * A-1 の回帰テスト。
 *
 * 「着地点として押させる半面は、打者の反対側」だけを固定する。
 * これが壊れると、セット2以降で打者自身の半面を着地点として押させる状態に戻る。
 * ラベルと色は正しく出てしまうので、**画面では絶対に気づけない**。
 */
import { describe, it, expect } from 'vitest'
import { computePlayerASide, hitterSide, landingSide, landingCourtMode } from '../courtSides'

describe('computePlayerASide', () => {
  it('第1セットは初期サイドのまま', () => {
    expect(computePlayerASide('bottom', 1, 0, 0)).toBe('bottom')
    expect(computePlayerASide('top', 1, 5, 3)).toBe('top')
  })

  it('セットごとに入れ替わる', () => {
    expect(computePlayerASide('bottom', 2, 0, 0)).toBe('top')
    expect(computePlayerASide('bottom', 3, 0, 0)).toBe('bottom')
  })

  it('第3セットは11点でもう一度入れ替わる', () => {
    expect(computePlayerASide('bottom', 3, 10, 8)).toBe('bottom')
    expect(computePlayerASide('bottom', 3, 11, 8)).toBe('top')
    expect(computePlayerASide('bottom', 3, 8, 11)).toBe('top')
  })
})

describe('landingSide — 着地点は必ず打者の反対側', () => {
  const sides = ['top', 'bottom'] as const
  const players = ['player_a', 'player_b'] as const

  it('全組合せで打者側と一致しない', () => {
    for (const aSide of sides) {
      for (const p of players) {
        expect(landingSide(aSide, p)).not.toBe(hitterSide(aSide, p))
      }
    }
  })

  it('第1セット (A が下) は従来通り', () => {
    const a1 = computePlayerASide('bottom', 1, 0, 0)
    expect(landingCourtMode(a1, 'player_a')).toBe('land')   // 上半面
    expect(landingCourtMode(a1, 'player_b')).toBe('hit')    // 下半面
  })

  it('第2セットは反転する (ここが A-1 の本体)', () => {
    const a2 = computePlayerASide('bottom', 2, 0, 0)
    expect(a2).toBe('top')
    // A は上に居るので、A が打ったら着地点は下半面
    expect(landingCourtMode(a2, 'player_a')).toBe('hit')
    expect(landingCourtMode(a2, 'player_b')).toBe('land')
  })

  it('第3セット11点のサイドチェンジにも追従する', () => {
    const before = computePlayerASide('bottom', 3, 10, 9)
    const after = computePlayerASide('bottom', 3, 11, 9)
    expect(landingCourtMode(before, 'player_a')).not.toBe(landingCourtMode(after, 'player_a'))
  })
})
