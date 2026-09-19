/**
 * A-8: `stroke.player === 'player_a' ? A : B` の二択がダブルスで壊れる。
 *
 * ダブルスでは `stroke.player` に `partner_a` / `partner_b` が入る。
 * 二択で書くと partner_a は else に落ちて B 扱いになる。実際に起きていたのは:
 *
 *   - ラリー終了パネルの「最終打者」に **相手の名前**が出て、操作者はそれを
 *     見て勝者を選んでいた
 *   - モバイル Pass3 の次打者計算が `partner_a` → `player_a` を返し、
 *     **同じチームに打ち返した**ことになっていた
 *
 * どちらも画面上はもっともらしい表示のままなので気づけない。
 */
import { describe, it, expect } from 'vitest'

import { normalizeStrikerTeam, nextStrikingTeam, opposingTeam, teamLetter } from '../players'

describe('normalizeStrikerTeam', () => {
  it('partner は所属チームに寄せる', () => {
    expect(normalizeStrikerTeam('partner_a')).toBe('player_a')
    expect(normalizeStrikerTeam('partner_b')).toBe('player_b')
  })

  it('シングルスの値はそのまま', () => {
    expect(normalizeStrikerTeam('player_a')).toBe('player_a')
    expect(normalizeStrikerTeam('player_b')).toBe('player_b')
  })

  it('知らない値は undefined — 既定のチームに倒さない', () => {
    for (const v of [undefined, null, '', 'player_c', 'PLAYER_A', 'partner']) {
      expect(normalizeStrikerTeam(v)).toBeUndefined()
    }
  })
})

describe('nextStrikingTeam', () => {
  it('partner_a の次は相手チーム', () => {
    // 旧実装 (`=== 'player_a' ? 'player_b' : 'player_a'`) はここで player_a を返し、
    // 同じチームが連続して打ったことになっていた。
    expect(nextStrikingTeam('partner_a', 'player_a')).toBe('player_b')
    expect(nextStrikingTeam('partner_b', 'player_a')).toBe('player_a')
  })

  it('シングルスでも従来どおり反転する', () => {
    expect(nextStrikingTeam('player_a', 'player_b')).toBe('player_b')
    expect(nextStrikingTeam('player_b', 'player_a')).toBe('player_a')
  })

  it('直前の打者が分からなければ fallback (= サーバー)', () => {
    expect(nextStrikingTeam(undefined, 'player_b')).toBe('player_b')
    expect(nextStrikingTeam('nonsense', 'player_a')).toBe('player_a')
  })

  it('同じチームを返さない', () => {
    for (const prev of ['player_a', 'partner_a', 'player_b', 'partner_b']) {
      const team = normalizeStrikerTeam(prev)!
      expect(nextStrikingTeam(prev, 'player_a')).not.toBe(team)
    }
  })
})

describe('teamLetter', () => {
  it('partner も所属チームの記号', () => {
    expect(teamLetter('partner_a')).toBe('A')
    expect(teamLetter('partner_b')).toBe('B')
  })

  it('不明は A に倒さず ? を返す', () => {
    expect(teamLetter(undefined)).toBe('?')
    expect(teamLetter('player_c')).toBe('?')
  })
})

describe('opposingTeam', () => {
  it('往復すると元に戻る', () => {
    expect(opposingTeam(opposingTeam('player_a'))).toBe('player_a')
    expect(opposingTeam('player_a')).toBe('player_b')
  })
})
