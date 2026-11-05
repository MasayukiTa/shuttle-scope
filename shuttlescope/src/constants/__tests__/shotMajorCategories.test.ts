import { describe, it, expect } from 'vitest'
import {
  MAJOR_SHOTS,
  MAJOR_REPRESENTATIVE,
  MAJOR_OF_CANONICAL,
  MAJOR_SHOT_JA,
  majorOf,
  representativeOf,
  type MajorShot,
} from '@/constants/shotMajorCategories'

// 18 canonical 小分類（shot_taxonomy.py の CANONICAL_SHOTS と同一）。
// ここがずれたらバックとの一致テスト (test_shot_major_categories.py) が落ちる。
const CANONICAL_SHOTS = [
  'short_service', 'long_service', 'net_shot', 'clear', 'push_rush', 'smash',
  'defensive', 'drive', 'lob', 'drop', 'cross_net', 'slice', 'around_head',
  'cant_reach', 'flick', 'half_smash', 'block', 'other',
] as const

describe('shotMajorCategories', () => {
  it('has exactly 9 major categories', () => {
    expect(MAJOR_SHOTS).toHaveLength(9)
    expect(new Set(MAJOR_SHOTS).size).toBe(9)
  })

  it('MAJOR_OF_CANONICAL covers every canonical shot exactly once', () => {
    const keys = Object.keys(MAJOR_OF_CANONICAL).sort()
    expect(keys).toEqual([...CANONICAL_SHOTS].sort())
  })

  it('every MAJOR_OF_CANONICAL value is a valid major', () => {
    for (const major of Object.values(MAJOR_OF_CANONICAL)) {
      expect(MAJOR_SHOTS).toContain(major)
    }
  })

  it('every major has a representative canonical shot', () => {
    for (const major of MAJOR_SHOTS) {
      expect(CANONICAL_SHOTS).toContain(MAJOR_REPRESENTATIVE[major])
    }
  })

  it('representative round-trips back to its own major', () => {
    // major -> representative -> major が恒等（代表値は必ずその大分類に属する）
    for (const major of MAJOR_SHOTS) {
      expect(majorOf(MAJOR_REPRESENTATIVE[major])).toBe(major)
    }
  })

  it('majorOf falls back to other for unknown', () => {
    expect(majorOf('nonexistent' as never)).toBe('other')
  })

  it('representativeOf returns a canonical for every major', () => {
    for (const major of MAJOR_SHOTS) {
      expect(representativeOf(major)).toBe(MAJOR_REPRESENTATIVE[major])
    }
  })

  it('every major has a JA label', () => {
    for (const major of MAJOR_SHOTS) {
      expect(MAJOR_SHOT_JA[major as MajorShot]).toBeTruthy()
    }
  })

  it('known mappings are stable', () => {
    expect(majorOf('half_smash')).toBe('smash')
    expect(majorOf('around_head')).toBe('smash')
    expect(majorOf('cross_net')).toBe('net')
    expect(majorOf('flick')).toBe('net')
    expect(majorOf('slice')).toBe('clear')
    expect(majorOf('long_service')).toBe('serve')
    expect(majorOf('cant_reach')).toBe('other')
    expect(representativeOf('serve')).toBe('short_service')
    expect(representativeOf('net')).toBe('net_shot')
  })
})
