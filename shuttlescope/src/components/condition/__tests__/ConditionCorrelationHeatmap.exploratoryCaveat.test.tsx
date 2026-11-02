/**
 * 監査 218: 相関ヒートマップは N が小さく多数のペアを同時探索するため、
 * 「探索的・多重比較未補正」の注記を常に表示する。
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
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

const rows = Array.from({ length: 8 }, (_v, i) => ({
  sleep_hours: 6 + (i % 3),
  weight_kg: 60 + (i % 4),
  session_rpe: 4 + (i % 2),
})) as unknown as import('@/hooks/useConditions').ConditionRecord[]

vi.mock('@/hooks/useConditions', () => ({
  useConditions: () => ({ data: rows, isLoading: false, error: null }),
}))

import { ConditionCorrelationHeatmap } from '../ConditionCorrelationHeatmap'

describe('ConditionCorrelationHeatmap exploratory caveat (監査 218)', () => {
  it('相関行列を表示するとき探索的・多重比較未補正の注記が出る', () => {
    render(<ConditionCorrelationHeatmap playerId={1} isLight={false} />)
    const caveat = ja.condition.corr_heatmap.exploratory_caveat
    expect(screen.getByText(caveat)).toBeTruthy()
  })

  it('exploratory_caveat キーが ja/en 両方に存在する', () => {
    expect(typeof ja.condition.corr_heatmap.exploratory_caveat).toBe('string')
    expect(typeof en.condition.corr_heatmap.exploratory_caveat).toBe('string')
    expect(ja.condition.corr_heatmap.exploratory_caveat.length).toBeGreaterThan(0)
    expect(en.condition.corr_heatmap.exploratory_caveat.length).toBeGreaterThan(0)
  })
})
