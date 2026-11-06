import { describe, it, expect } from 'vitest'
import { classifyExportMatch, isValidMatchDate } from '../exportCandidates'

describe('classifyExportMatch', () => {
  it('通常の試合は valid', () => {
    expect(classifyExportMatch({ date: '2026-04-15', tournament: '全日本総合', result: 'win' })).toBe('valid')
    expect(classifyExportMatch({ date: '2026-04-15', tournament: 'Testing Cup', result: 'loss' })).toBe('valid')
  })

  it('不正な日付は invalid_date', () => {
    for (const date of ['0001-01-01', '', null, undefined, 'abc']) {
      expect(classifyExportMatch({ date, tournament: 'T', result: 'win' })).toBe('invalid_date')
    }
  })

  it('検証用の大会名は internal', () => {
    for (const tournament of ['BIAS_SEED_20260415_SINGLES_1', 'DEMO 大会', 'test-cup', 'テスト大会', 'デモ']) {
      expect(classifyExportMatch({ date: '2026-04-15', tournament, result: 'win' })).toBe('internal')
    }
  })

  it('未完了は unfinished', () => {
    expect(classifyExportMatch({ date: '2026-04-15', tournament: '大会', result: 'unfinished' })).toBe('unfinished')
  })

  it('複数に当てはまるときは日付不正を優先する', () => {
    expect(classifyExportMatch({ date: '0001-01-01', tournament: 'BIAS_SEED_1', result: 'unfinished' })).toBe('invalid_date')
  })
})


describe('isValidMatchDate', () => {
  it('1900 年以降のパース可能な日付は true', () => {
    expect(isValidMatchDate('2026-04-15')).toBe(true)
    expect(isValidMatchDate('1900-01-01')).toBe(true)
  })

  it('0001-01-01 や欠損・不正値は false', () => {
    for (const date of ['0001-01-01', '1899-12-31', '', null, undefined, 'abc']) {
      expect(isValidMatchDate(date)).toBe(false)
    }
  })
})
