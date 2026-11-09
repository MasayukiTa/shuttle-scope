import { describe, expect, it } from 'vitest'

import { deriveSyncStatus } from '../syncStatus'

describe('deriveSyncStatus', () => {
  it('\u30aa\u30d5\u30e9\u30a4\u30f3\u306f\u672a\u9001\u4fe1\u304c 0 \u3067\u3082 offline \u3067\u76ee\u7acb\u3064', () => {
    const v = deriveSyncStatus({ unsentCount: 0, offline: true, lastSendFailed: false })
    expect(v.state).toBe('offline')
    expect(v.prominent).toBe(true)
  })

  it('\u30aa\u30f3\u30e9\u30a4\u30f3\u3067\u76f4\u8fd1\u9001\u4fe1\u5931\u6557\u304b\u3064\u672a\u9001\u4fe1\u304c\u6b8b\u308b\u3068 failed', () => {
    const v = deriveSyncStatus({ unsentCount: 3, offline: false, lastSendFailed: true })
    expect(v.state).toBe('failed')
    expect(v.unsentCount).toBe(3)
    expect(v.prominent).toBe(true)
  })

  it('\u9001\u4fe1\u5931\u6557\u3057\u3066\u3082\u672a\u9001\u4fe1\u304c 0 \u306a\u3089 saved', () => {
    const v = deriveSyncStatus({ unsentCount: 0, offline: false, lastSendFailed: true })
    expect(v.state).toBe('saved')
    expect(v.prominent).toBe(false)
  })

  it('\u30aa\u30f3\u30e9\u30a4\u30f3\u30fb\u5931\u6557\u306a\u3057\u306f saved', () => {
    const v = deriveSyncStatus({ unsentCount: 0, offline: false, lastSendFailed: false })
    expect(v.state).toBe('saved')
  })

  it('offline \u306f lastSendFailed \u3088\u308a\u512a\u5148\u3055\u308c\u308b', () => {
    const v = deriveSyncStatus({ unsentCount: 2, offline: true, lastSendFailed: true })
    expect(v.state).toBe('offline')
  })

  it('\u672a\u9001\u4fe1\u4ef6\u6570\u306f\u8ca0\u30fb\u975e\u6574\u6570\u3092\u6b63\u898f\u5316\u3059\u308b', () => {
    expect(deriveSyncStatus({ unsentCount: -5, offline: false, lastSendFailed: false }).unsentCount).toBe(0)
    expect(deriveSyncStatus({ unsentCount: 2.9, offline: true, lastSendFailed: false }).unsentCount).toBe(2)
    expect(deriveSyncStatus({ unsentCount: NaN, offline: true, lastSendFailed: false }).unsentCount).toBe(0)
  })
})
