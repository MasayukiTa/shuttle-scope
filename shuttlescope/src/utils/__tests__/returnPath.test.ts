/**
 * G4 #715: ログイン後に元のページに戻る判定。
 *
 * normal / MFA はどちらも同じ resolveReturnPath を通る (ログイン経路に依らず
 * 同一ユーザー + 同意完了 + 許可ルート だけ戻る) ため、純ロジックで網羅する。
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  consumeReturnContext,
  isAllowedReturnPath,
  resolveReturnPath,
  storeReturnContext,
  RETURN_PATH_KEY,
  RETURN_USER_KEY,
} from '../returnPath'

afterEach(() => {
  vi.unstubAllGlobals()
})

function fakeSessionStorage() {
  const m = new Map<string, string>()
  vi.stubGlobal('sessionStorage', {
    getItem: (k: string) => (m.has(k) ? m.get(k)! : null),
    setItem: (k: string, v: string) => void m.set(k, String(v)),
    removeItem: (k: string) => void m.delete(k),
  })
  return m
}

describe('isAllowedReturnPath', () => {
  it('許可 in-app ルートを通す', () => {
    expect(isAllowedReturnPath('/matches')).toBe(true)
    expect(isAllowedReturnPath('/dashboard/review')).toBe(true)
    expect(isAllowedReturnPath('/annotator/12')).toBe(true)
    expect(isAllowedReturnPath('/settings')).toBe(true)
  })

  it('外部 URL ・ protocol-relative ・相対パス を弾く', () => {
    expect(isAllowedReturnPath('https://evil.example.com/')).toBe(false)
    expect(isAllowedReturnPath('//evil.example.com')).toBe(false)
    expect(isAllowedReturnPath('matches')).toBe(false)
    expect(isAllowedReturnPath('')).toBe(false)
    expect(isAllowedReturnPath(null)).toBe(false)
    expect(isAllowedReturnPath(undefined)).toBe(false)
  })

  it('未知ルートや境界を越えた前方一致を弾く', () => {
    expect(isAllowedReturnPath('/login')).toBe(false)
    expect(isAllowedReturnPath('/nope')).toBe(false)
    // '/users' は許可だが '/users-evil' は別パス
    expect(isAllowedReturnPath('/users-evil')).toBe(false)
    expect(isAllowedReturnPath('/users')).toBe(true)
    expect(isAllowedReturnPath('/users/pending')).toBe(true)
  })
})

describe('resolveReturnPath', () => {
  const ctx = { path: '/dashboard/review', userId: '7' }

  it('同一ユーザー + 同意完了 + 許可パス なら戻る (normal/MFA 共通)', () => {
    expect(resolveReturnPath(ctx, '7', true)).toBe('/dashboard/review')
  })

  it('別ユーザーなら null', () => {
    expect(resolveReturnPath(ctx, '8', true)).toBeNull()
  })

  it('同意未完了なら null', () => {
    expect(resolveReturnPath(ctx, '7', false)).toBeNull()
  })

  it('不正パス (外部 URL) なら null', () => {
    expect(resolveReturnPath({ path: 'https://evil.example.com', userId: '7' }, '7', true)).toBeNull()
  })

  it('ctx が無ければ null', () => {
    expect(resolveReturnPath(null, '7', true)).toBeNull()
  })

  it('現在ユーザー不明なら null', () => {
    expect(resolveReturnPath(ctx, null, true)).toBeNull()
  })
})

describe('store / consume', () => {
  it('許可パスは保存され、1 回読むと消費される', () => {
    fakeSessionStorage()
    storeReturnContext('7', '/annotator/5')
    const first = consumeReturnContext()
    expect(first).toEqual({ path: '/annotator/5', userId: '7' })
    // 消費済み
    expect(consumeReturnContext()).toBeNull()
  })

  it('不正パス / userId 空 は保存しない', () => {
    const m = fakeSessionStorage()
    storeReturnContext('7', 'https://evil.example.com')
    expect(m.has(RETURN_PATH_KEY)).toBe(false)
    storeReturnContext('', '/matches')
    expect(m.has(RETURN_USER_KEY)).toBe(false)
  })
})
