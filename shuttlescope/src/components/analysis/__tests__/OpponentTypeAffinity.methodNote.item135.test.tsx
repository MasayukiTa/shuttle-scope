/**
 * 監査 #135: 対戦相手タブの手法説明が「統計的クラスタリング」と「ルールベース」で自己矛盾する問題への固定テスト。
 * auto_type_note がグループ生成とグループ命名の2段階を明記することを固定する。
 */
import { describe, it, expect } from 'vitest'
import ja from '@/i18n/ja.json'
import en from '@/i18n/en.json'

type Dict = Record<string, unknown>
function lookup(dict: Dict, key: string): string {
  const v = key.split('.').reduce<unknown>((o, k) => (o as Dict | undefined)?.[k], dict)
  return typeof v === 'string' ? v : key
}

const KEY = 'auto.OpponentTypeAffinity.auto_type_note'

describe('i18n key parity (#135)', () => {
  it('auto_type_note が ja/en 両方にある', () => {
    for (const dict of [ja, en] as Dict[]) {
      expect(lookup(dict, KEY)).not.toBe(KEY)
    }
  })

  it('ja は2段階（生成と命名）を明記し、統計的クラスタリングを否定する', () => {
    const s = lookup(ja as Dict, KEY)
    expect(s).toContain('グループ生成')
    expect(s).toContain('グループ命名')
    expect(s).toContain('統計的クラスタリングは使用していません')
  })

  it('en は2段階（grouping と naming）を明記し、統計的クラスタリングを否定する', () => {
    const s = lookup(en as Dict, KEY).toLowerCase()
    expect(s).toContain('grouping')
    expect(s).toContain('naming')
    expect(s).toContain('no statistical clustering')
  })
})
