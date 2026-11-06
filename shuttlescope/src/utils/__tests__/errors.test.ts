import { describe, it, expect } from 'vitest'
import { isTransientSaveError, errorMessage, errorStatus } from '../errors'

/**
 * 要望2 (保存し終わったはずが「保存失敗」と出る) の中核判定。
 *
 * 記録入力の保存は、送信前に端末へ退避し安定した冪等キーで送る。サーバ受理後に
 * 応答が届かない (タイムアウト・通信断) 失敗は、サーバ側は保存済みのことがあり、
 * 退避が残って自動再送されるため「保存失敗」と断定してはいけない (= transient)。
 * 冪等キーで送り直しても直らない 4xx だけを恒久的な失敗 (= not transient) とする。
 */
describe('isTransientSaveError', () => {
  it('ステータスを持たない失敗 (タイムアウト・通信断) は一過性', () => {
    expect(isTransientSaveError(new Error('API timeout (60000ms): /strokes/batch'))).toBe(true)
    expect(isTransientSaveError(new TypeError('Failed to fetch'))).toBe(true)
    expect(isTransientSaveError(null)).toBe(true)
    expect(isTransientSaveError(undefined)).toBe(true)
    expect(isTransientSaveError('offline')).toBe(true)
  })

  it('5xx は一過性 (サーバ一時障害、再送で解決しうる)', () => {
    for (const status of [500, 502, 503, 504]) {
      expect(isTransientSaveError({ status })).toBe(true)
    }
  })

  it('408 Request Timeout と 429 Too Many Requests は一過性', () => {
    expect(isTransientSaveError({ status: 408 })).toBe(true)
    expect(isTransientSaveError({ status: 429 })).toBe(true)
  })

  it('その他の 4xx は恒久的 (冪等再送でも直らない本当の失敗)', () => {
    for (const status of [400, 401, 403, 404, 409, 422]) {
      expect(isTransientSaveError({ status })).toBe(false)
    }
  })

  it('境界値: 400 は恒久的、399 と 500 は一過性', () => {
    expect(isTransientSaveError({ status: 399 })).toBe(true)
    expect(isTransientSaveError({ status: 400 })).toBe(false)
    expect(isTransientSaveError({ status: 499 })).toBe(false)
    expect(isTransientSaveError({ status: 500 })).toBe(true)
  })

  it('useOfflineSync の permanent 判定と境界が一致する', () => {
    // useOfflineSync: status>=400 && <500 && !==408 && !==429 を permanent として扱う。
    // isTransientSaveError はその補集合を transient とする。両者の境界を固定する。
    const permanentStatuses = [400, 401, 403, 404, 409, 422, 499]
    const transientStatuses = [408, 429, 500, 503]
    for (const s of permanentStatuses) expect(isTransientSaveError({ status: s })).toBe(false)
    for (const s of transientStatuses) expect(isTransientSaveError({ status: s })).toBe(true)
  })
})

describe('errorStatus / errorMessage (回帰)', () => {
  it('status を持つエラーから数値を取り出す', () => {
    expect(errorStatus({ status: 404 })).toBe(404)
    expect(errorStatus(new Error('x'))).toBeUndefined()
  })

  it('message を取り出し、無ければ fallback', () => {
    expect(errorMessage(new Error('boom'))).toBe('boom')
    expect(errorMessage({}, 'fallback')).toBe('fallback')
  })
})
