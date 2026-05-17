import { describe, it, expect } from 'vitest'
import {
  setWinner, isDeuce, isGoldenPoint, isSetPoint,
  matchWinner, serveSide, isFinalSetMidChange, isMidGameBreak,
} from '../badmintonRules'

describe('badminton rules', () => {
  describe('setWinner', () => {
    it('21-19 で A 勝ち', () => {
      expect(setWinner({ scoreA: 21, scoreB: 19 })).toBe('A')
    })
    it('20-22 はデュース後 B 勝ち', () => {
      expect(setWinner({ scoreA: 20, scoreB: 22 })).toBe('B')
    })
    it('21-20 はまだ勝ちでない (2点差不足)', () => {
      expect(setWinner({ scoreA: 21, scoreB: 20 })).toBe(null)
    })
    it('29-29 はまだ勝ちでない', () => {
      expect(setWinner({ scoreA: 29, scoreB: 29 })).toBe(null)
    })
    it('30-29 で A 勝ち (golden point)', () => {
      expect(setWinner({ scoreA: 30, scoreB: 29 })).toBe('A')
    })
    it('0-0 は当然進行中', () => {
      expect(setWinner({ scoreA: 0, scoreB: 0 })).toBe(null)
    })
  })

  describe('isDeuce', () => {
    it('20-20 はデュース', () => expect(isDeuce({ scoreA: 20, scoreB: 20 })).toBe(true))
    it('22-22 もデュース継続', () => expect(isDeuce({ scoreA: 22, scoreB: 22 })).toBe(true))
    it('20-19 はまだデュースではない', () => expect(isDeuce({ scoreA: 20, scoreB: 19 })).toBe(false))
    it('30-29 は golden で deuce 状態は終わってる', () => expect(isDeuce({ scoreA: 30, scoreB: 29 })).toBe(false))
  })

  describe('isGoldenPoint', () => {
    it('29-29 のみ true', () => {
      expect(isGoldenPoint({ scoreA: 29, scoreB: 29 })).toBe(true)
      expect(isGoldenPoint({ scoreA: 28, scoreB: 29 })).toBe(false)
    })
  })

  describe('isSetPoint', () => {
    it('20-18 は A の setPoint', () => expect(isSetPoint({ scoreA: 20, scoreB: 18 })).toBe('A'))
    it('21-21 はどちらでもない (deuce, 同点)', () => expect(isSetPoint({ scoreA: 21, scoreB: 21 })).toBe(null))
    it('22-21 は A の setPoint (deuce で 1 点リード)', () => expect(isSetPoint({ scoreA: 22, scoreB: 21 })).toBe('A'))
    it('29-x は A の setPoint', () => expect(isSetPoint({ scoreA: 29, scoreB: 15 })).toBe('A'))
  })

  describe('matchWinner', () => {
    it('best-of-3 で 2-0', () => {
      expect(matchWinner({ completedSetWinners: ['A', 'A'], bestOf: 3 })).toBe('A')
    })
    it('best-of-3 で 1-1 はまだ', () => {
      expect(matchWinner({ completedSetWinners: ['A', 'B'], bestOf: 3 })).toBe(null)
    })
    it('best-of-3 で 2-1', () => {
      expect(matchWinner({ completedSetWinners: ['A', 'B', 'B'], bestOf: 3 })).toBe('B')
    })
    it('best-of-5 で 3-0', () => {
      expect(matchWinner({ completedSetWinners: ['A', 'A', 'A'], bestOf: 5 })).toBe('A')
    })
    it('default bestOf=3', () => {
      expect(matchWinner({ completedSetWinners: ['A', 'A'] })).toBe('A')
    })
  })

  describe('serveSide', () => {
    it('A serve 偶数 → right', () => {
      expect(serveSide('A', { scoreA: 0, scoreB: 5 })).toBe('right')
      expect(serveSide('A', { scoreA: 2, scoreB: 7 })).toBe('right')
    })
    it('A serve 奇数 → left', () => {
      expect(serveSide('A', { scoreA: 1, scoreB: 0 })).toBe('left')
    })
    it('B serve は B のスコアで判定', () => {
      expect(serveSide('B', { scoreA: 5, scoreB: 4 })).toBe('right')
      expect(serveSide('B', { scoreA: 5, scoreB: 3 })).toBe('left')
    })
  })

  describe('isFinalSetMidChange', () => {
    it('best-of-3 の第3セットで 11 点に到達でコートチェンジ', () => {
      expect(isFinalSetMidChange(3, 3, { scoreA: 11, scoreB: 5 })).toBe(true)
    })
    it('第1セットでは false', () => {
      expect(isFinalSetMidChange(1, 3, { scoreA: 11, scoreB: 5 })).toBe(false)
    })
    it('最終ゲームでも 10 点未満なら false', () => {
      expect(isFinalSetMidChange(3, 3, { scoreA: 10, scoreB: 9 })).toBe(false)
    })
  })

  describe('isMidGameBreak', () => {
    it('11 点でブレイク', () => expect(isMidGameBreak({ scoreA: 11, scoreB: 5 })).toBe(true))
    it('12 点はブレイクではない (既に過ぎてる)', () => expect(isMidGameBreak({ scoreA: 12, scoreB: 5 })).toBe(false))
  })
})
