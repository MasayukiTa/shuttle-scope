import { describe, it, expect } from 'vitest'
import { countQueuedForSet, isSetEndBlockedBySave, classifyConfirmSaveFailure } from '../liveSetEndGuard'

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

describe('classifyConfirmSaveFailure (要望2: 保存失敗の誤表示是正)', () => {
  it('タイムアウト・通信断は再送待ち扱い (保存失敗を出さない)', () => {
    const timeout = classifyConfirmSaveFailure(new Error('API timeout (60000ms): /strokes/batch'))
    expect(timeout).toEqual({ pushSaveError: false, saveFailed: false, pendingResend: true })

    const offline = classifyConfirmSaveFailure(new TypeError('Failed to fetch'))
    expect(offline).toEqual({ pushSaveError: false, saveFailed: false, pendingResend: true })
  })

  it('5xx / 408 / 429 は再送待ち扱い', () => {
    for (const status of [500, 503, 408, 429]) {
      expect(classifyConfirmSaveFailure({ status })).toEqual({
        pushSaveError: false,
        saveFailed: false,
        pendingResend: true,
      })
    }
  })

  it('その他の 4xx は恒久的な保存失敗として出す', () => {
    for (const status of [400, 401, 403, 404, 409, 422]) {
      expect(classifyConfirmSaveFailure({ status })).toEqual({
        pushSaveError: true,
        saveFailed: true,
        pendingResend: false,
      })
    }
  })

  it('保存失敗と再送待ちは排他 (両方同時に立たない)', () => {
    for (const err of [new Error('timeout'), { status: 500 }, { status: 404 }, { status: 400 }]) {
      const d = classifyConfirmSaveFailure(err)
      expect(d.saveFailed && d.pendingResend).toBe(false)
      // pushSaveError は saveFailed と一致する (保存失敗のときだけ一覧に積む)
      expect(d.pushSaveError).toBe(d.saveFailed)
    }
  })
})
