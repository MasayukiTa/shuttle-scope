/**
 * 試合展開パターンの文言が i18n 経由で出ること、
 * ピア比較カードの指標名・単位が、バックエンドの返す全キーぶん ja / en にあること。
 */
import { describe, it, expect, vi } from 'vitest'
import { render } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import ja from '@/i18n/ja.json'
import en from '@/i18n/en.json'

type Dict = Record<string, unknown>
function lookup(dict: Dict, key: string): string {
  const v = key.split('.').reduce<unknown>((o, k) => (o as Dict | undefined)?.[k], dict)
  return typeof v === 'string' ? v : key
}
function interp(s: string, o?: Record<string, unknown>): string {
  return s.replace(/\{\{(\w+)\}\}/g, (_m, k) => String(o?.[k] ?? ''))
}

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, o?: Record<string, unknown>) => interp(lookup(ja as Dict, key), o),
  }),
}))

import { MatchScriptBlock } from '../MatchScriptBlock'

describe('MatchScriptBlock: 文言は i18n から出る', () => {
  it('疲労データなしで優勢のとき、固定の日本語説明と補足を出す', () => {
    const { container } = render(<MatchScriptBlock winProbability={0.7} fatigueBreakdown={null} />)
    const text = container.textContent ?? ''
    expect(text).toContain('優勢型')
    expect(text).toContain('過去の実績では有利です')
    expect(text).toContain('試合展開の詳細は表示していません')
    // 未登録キーがそのまま出ていないこと
    expect(text).not.toContain('prediction.')
  })

  it('疲労データありのとき、低下率のチップを件数つきで出す', () => {
    const { container } = render(
      <MatchScriptBlock
        winProbability={0.58}
        fatigueBreakdown={{ temporal_drop: 0.12, long_rally_penalty: 0.02, pressure_drop: 0.0, total_rallies: 40 }}
      />,
    )
    const text = container.textContent ?? ''
    expect(text).toContain('序盤優勢・後半注意型')
    expect(text).toContain('後半の失速 12%')
    expect(text).not.toContain('prediction.')
  })
})

describe('ピア比較: 指標名・単位の翻訳', () => {
  const py = readFileSync(resolve(process.cwd(), 'backend/analysis/peer_comparison.py'), 'utf-8')
  const block = py.match(/SUPPORTED_METRICS[^=]*=\s*\(([^)]*)\)/)
  const metrics = block ? [...block[1].matchAll(/"([a-z_]+)"/g)].map((m) => m[1]) : []
  const units = [...py.matchAll(/METRIC_UNITS[\s\S]*?\{([\s\S]*?)\}/g)]
    .flatMap((m) => [...m[1].matchAll(/:\s*"([a-z_]+)"/g)].map((x) => x[1]))

  it('バックエンドの全指標キーと全単位に、日本語と英語の表示名がある', () => {
    expect(metrics.length).toBeGreaterThan(0)
    expect(units.length).toBeGreaterThan(0)
    for (const dict of [ja, en] as Dict[]) {
      for (const m of metrics) expect(lookup(dict, `auto.PeerComparisonCard.metric_${m}`)).not.toContain('metric_')
      for (const u of new Set(units)) expect(lookup(dict, `auto.PeerComparisonCard.unit_${u}`)).not.toContain('unit_')
      expect(lookup(dict, 'auto.PeerComparisonCard.metric_unknown')).not.toContain('metric_unknown')
    }
  })
})
