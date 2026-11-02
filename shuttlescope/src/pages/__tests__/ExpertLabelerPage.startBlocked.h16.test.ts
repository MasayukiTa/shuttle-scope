/**
 * audit #176: Expert Labeler 一覧の「開始」CTA が行き止まりを生まないことを固定する。
 * clips_pending (対象・動画はあるがクリップ未生成) で開始すると詳細画面が
 * no_clips (「クリップがありません」) の行き止まりになるため、一覧でブロックする。
 */
import { describe, it, expect } from 'vitest'
import { isStartBlocked } from '../ExpertLabelerPage'

describe('ExpertLabelerPage isStartBlocked (audit #176)', () => {
  it('clips_pending は開始をブロックする (行き止まり防止)', () => {
    expect(isStartBlocked('clips_pending')).toBe(true)
  })
  it('no_targets / no_video もブロックする', () => {
    expect(isStartBlocked('no_targets')).toBe(true)
    expect(isStartBlocked('no_video')).toBe(true)
  })
  it('ready だけ開始できる', () => {
    expect(isStartBlocked('ready')).toBe(false)
  })
})
