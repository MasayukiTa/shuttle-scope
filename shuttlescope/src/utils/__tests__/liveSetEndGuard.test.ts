import { describe, it, expect } from 'vitest'
import { countQueuedForSet, isSetEndBlockedBySave } from '../liveSetEndGuard'

describe('isSetEndBlockedBySave (監査 #722)', () => {
  it('保存中・保存エラー・再送待ちがすべて 0 のときだけ許可する', () => {
    expect(isSetEndBlockedBySave({ pendingSaveCount: 0, saveErrorCount: 0, queuedForSet: 0 })).toBe(false)
  })

  it('最終ラリーが保存中ならブロックする', () => {
    expect(isSetEndBlockedBySave({ pendingSaveCount: 1, saveErrorCount: 0, queuedForSet: 0 })).toBe(true)
  })

  it('保存に失敗して未確認のエラーが残るならブロックする', () => {
    expect(isSetEndBlockedBySave({ pendingSaveCount: 0, saveErrorCount: 1, queuedForSet: 0 })).toBe(true)
  })

  it('端末に再送待ちが残るならブロックする', () => {
    expect(isSetEndBlockedBySave({ pendingSaveCount: 0, saveErrorCount: 0, queuedForSet: 2 })).toBe(true)
  })
})

describe('countQueuedForSet', () => {
  it('指定セットの退避行だけを数える', () => {
    const rows = [{ setId: 3 }, { setId: 4 }, { setId: 3 }]
    expect(countQueuedForSet(rows, 3)).toBe(2)
    expect(countQueuedForSet(rows, 9)).toBe(0)
    expect(countQueuedForSet([], 3)).toBe(0)
  })
})
