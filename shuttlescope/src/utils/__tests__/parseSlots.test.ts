import { describe, it, expect } from 'vitest'
import { parseShotType, parseZone, parseAllSlots } from '../parseSlots'

const NOW = new Date(2026, 4, 23) // 2026-05-23

describe('parseShotType', () => {
  it('matches スマッシュ', () => {
    const r = parseShotType('スマッシュの精度は?')
    expect(r?.code).toBe('smash')
  })
  it('matches english smash', () => {
    const r = parseShotType('How is my smash today?')
    expect(r?.code).toBe('smash')
  })
  it('rejects negation スマッシュ以外', () => {
    expect(parseShotType('スマッシュ以外のショット')).toBeNull()
  })
  it('matches ヘアピン as net', () => {
    expect(parseShotType('ヘアピンの精度')?.code).toBe('net')
  })
  it('returns null for unrelated', () => {
    expect(parseShotType('試合の結果')).toBeNull()
  })
})

describe('parseZone', () => {
  it('matches バック奥', () => {
    expect(parseZone('バック奥の打点は?')?.code).toBe('BR')
  })
  it('matches フォア前', () => {
    expect(parseZone('フォア前の処理')?.code).toBe('FL')
  })
  it('falls back to generic BACK', () => {
    expect(parseZone('コート奥のショット')?.code).toBe('BACK')
  })
  it('returns null for unrelated', () => {
    expect(parseZone('普通の質問')).toBeNull()
  })
})

describe('parseAllSlots', () => {
  it('extracts period + shotType + zone combined', () => {
    const r = parseAllSlots('先月のスマッシュ、バック奥は?', NOW)
    expect(r.period.dateFrom).toBe('2026-04-01')
    expect(r.shotType?.code).toBe('smash')
    expect(r.zone?.code).toBe('BR')
  })
  it('empty input → all null/none', () => {
    const r = parseAllSlots('', NOW)
    expect(r.period.confidence).toBe('none')
    expect(r.shotType).toBeNull()
    expect(r.zone).toBeNull()
  })
})
