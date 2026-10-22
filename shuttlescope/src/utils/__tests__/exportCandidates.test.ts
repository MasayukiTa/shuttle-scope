import { describe, it, expect } from 'vitest'
import { classifyExportMatch } from '../exportCandidates'

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
