/**
 * S-15: 「28日平均」は実際には直近28回の記録の平均。ラベルを正直にし、28回に満たないときは件数を出す。
 * S-13: 状態-行動価値(Q値)の最善手は最大値選択なので、選択バイアスの注意書きを出す。
 */
import { describe, it, expect, vi } from 'vitest'
import { render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
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
vi.mock('@/hooks/useAuth', () => ({ useAuth: () => ({ role: 'player' }) }))
vi.mock('@/api/client', () => ({ apiGet: vi.fn(), API_BASE_URL: '' }))
vi.mock('@/contexts/ResearchBundleContext', () => ({
  useResearchBundleSlice: () => ({
    slice: {
      success: true,
      data: [
        {
          state: { score_phase: 'mid', set_phase: 'first', rally_bucket: 'short', player_role: 'server' },
          best_action: 'smash', best_q: 0.1, best_q_ci_low: 0.0, best_q_ci_high: 0.2,
          n_actions: 2, n_reliable_actions: 2,
        },
      ],
      meta: { tier: 'research', evidence_level: 'exploratory', sample_size: 80, caution: null },
    },
    loading: false,
    provided: true,
  }),
}))

import { ConditionResult } from '../ConditionResult'
import { StateActionValueCard } from '@/components/analysis/StateActionValueCard'
import { DEFAULT_FILTERS } from '@/types'

const base = { ccs: 80, personal_range_low: 70, personal_range_high: 90, factors: [] }

describe('ConditionResult: 28 entries, not 28 days', () => {
  it('28件以上: 「直近28回」と書き、日数とは書かない', () => {
    const { container } = render(<ConditionResult result={{ ...base, delta_28ma: 2.5, n_28: 28 }} historyCount={30} />)
    const text = container.textContent ?? ''
    expect(text).toContain('直近28回の平均との差')
    expect(text).toContain('直近28回の記録')
    expect(text).not.toMatch(/28日/)
  })

  it('28件未満: 実際に使った件数を表示する', () => {
    const { container } = render(<ConditionResult result={{ ...base, delta_28ma: 2.5, n_28: 9 }} historyCount={9} />)
    const text = container.textContent ?? ''
    expect(text).toContain('直近9回の平均との差')
    expect(text).toContain('直近9回の記録')
    expect(text).not.toMatch(/28日/)
  })

  it('値が null のとき差の行を出さない (0.0 にしない)', () => {
    const { container } = render(<ConditionResult result={{ ...base, delta_28ma: null, n_28: null }} historyCount={3} />)
    expect(container.textContent ?? '').not.toContain('平均との差')
  })
})

describe('StateActionValueCard: selection-bias note', () => {
  it('最善手を出すときに注意書きを描く', () => {
    const qc = new QueryClient()
    const { getByTestId } = render(
      <QueryClientProvider client={qc}>
        <StateActionValueCard playerId={1} filters={DEFAULT_FILTERS} />
      </QueryClientProvider>,
    )
    expect(getByTestId('state-action-selection-note').textContent).toBe(
      '最大値を選んでいるため、実際より良く見える傾向があります。回数が少ないセルは参考程度に。',
    )
  })
})

describe('i18n: ja and en both carry the honest labels', () => {
  const keys = [
    'condition.result.personal_range_note',
    'condition.result.personal_range_note_n',
    'condition.result.delta_28ma',
    'condition.result.delta_28ma_n',
    'condition.insights.ccs_28ma',
    'auto.StateActionValueCard.selection_note',
  ]
  it.each(keys)('%s exists in ja and en', (k) => {
    expect(lookup(ja as Dict, k)).not.toBe(k)
    expect(lookup(en as Dict, k)).not.toBe(k)
  })
  it('no label claims 28 days for the record-based average', () => {
    for (const d of [ja, en] as Dict[]) {
      for (const k of ['condition.result.delta_28ma', 'condition.result.personal_range_note', 'condition.insights.ccs_28ma']) {
        expect(lookup(d, k)).not.toMatch(/28日|28[- ]day/i)
      }
    }
    expect(lookup(en as Dict, 'condition.result.delta_28ma')).toMatch(/last 28 entries/)
  })
})
