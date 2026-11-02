process.env.TZ = 'Asia/Tokyo'

import { describe, expect, it } from 'vitest'
import { formatJST } from '@/utils/datetime'

// 監査 #174: 承認待ち画面で登録日時が生 ISO (UTC) のまま表示されていた。
// formatJST が TZ なし naive ISO を UTC と解釈し JST へ変換することを固定する。
describe('formatJST (audit #174)', () => {
  it('converts a naive (no-TZ) UTC ISO string to JST, not raw', () => {
    const out = formatJST('2026-10-21T12:10:05.792511')
    // 12:10 UTC + 9h = 21:10 JST
    expect(out).toContain('21:10')
    expect(out).toContain('2026')
    // raw ISO must not leak
    expect(out).not.toContain('T12:10')
    expect(out).not.toContain('.792511')
  })

  it('honours an explicit Z suffix', () => {
    const out = formatJST('2026-10-21T00:00:00Z')
    expect(out).toContain('09:00')
  })

  it('honours an explicit +09:00 offset', () => {
    const out = formatJST('2026-10-21T21:10:05+09:00')
    expect(out).toContain('21:10')
  })

  it('returns empty string for null / empty', () => {
    expect(formatJST(null)).toBe('')
    expect(formatJST('')).toBe('')
  })
})
