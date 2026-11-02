import { describe, expect, it } from 'vitest'
import ja from '@/i18n/ja.json'
import en from '@/i18n/en.json'

// 監査 #175: 承認待ちカードに内部 enum "unverified" が生表示されていた。
// 表示用ラベルが raw enum でないことを固定する。
type Dict = Record<string, any>
const jaD = ja as Dict
const enD = en as Dict

describe('PendingUsersPage verification labels (audit #175)', () => {
  it('ja labels are localized, not the raw enum value', () => {
    const blk = jaD.auto.PendingUsersPage
    expect(blk.verified).not.toBe('verified')
    expect(blk.unverified).not.toBe('unverified')
    expect(blk.unverified).toBe('メール未確認')
    expect(blk.verified).toBe('確認済み')
  })

  it('en labels are human-readable, not the raw enum value', () => {
    const blk = enD.auto.PendingUsersPage
    expect(blk.verified).toBe('Verified')
    expect(blk.unverified).toBe('Not verified')
  })
})
