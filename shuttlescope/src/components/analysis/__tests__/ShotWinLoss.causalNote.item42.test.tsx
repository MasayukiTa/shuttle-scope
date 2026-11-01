/**
 * 監査 #42: ショット別勝率が因果的な「ショット有効性」に見えすぎる問題への固定テスト。
 * ラベルが「ショット使用時のラリー結果」へ名称変更され、因果でない旨の定義注記が t() 経由で表示されることを固定する。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ja from '@/i18n/ja.json'
import en from '@/i18n/en.json'

type Dict = Record<string, unknown>
function lookup(dict: Dict, key: string, vars?: Record<string, unknown>): string {
  const v = key.split('.').reduce<unknown>((o, k) => (o as Dict | undefined)?.[k], dict)
  let s = typeof v === 'string' ? v : key
  if (vars) for (const [k, val] of Object.entries(vars)) s = s.replace(new RegExp('{{\\s*' + k + '\\s*}}', 'g'), String(val))
  return s
}

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, vars?: Record<string, unknown>) => lookup(en as Dict, key, vars),
    i18n: { language: 'en' },
  }),
}))

vi.mock('@/api/client', () => ({ apiGet: vi.fn(), API_BASE_URL: '' }))
vi.mock('@/hooks/useIsLightMode', () => ({ useIsLightMode: () => false }))

import * as apiClient from '@/api/client'
import { DEFAULT_FILTERS } from '@/types'
import { ShotWinLoss } from '../ShotWinLoss'

const mockApi = vi.mocked(apiClient.apiGet)

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

const RESP = {
  data: [
    { shot_type: 'roundhead', shot_type_ja: 'Roundhead', total: 50, win_count: 44, lose_count: 6, win_rate: 0.878 },
  ],
  meta: { sample_size: 50, confidence: { level: 'high', stars: '***', label: 'high' } },
}

beforeEach(() => { mockApi.mockReset() })

describe('i18n key parity (#42)', () => {
  it('definition_note が ja/en 両方にある', () => {
    for (const dict of [ja, en] as Dict[]) {
      expect(lookup(dict, 'auto.ShotWinLoss.definition_note')).not.toBe('auto.ShotWinLoss.definition_note')
    }
  })
  it('DashboardAdvancedPage.k1 が因果を示さない表現へ変更されている', () => {
    const jaLabel = lookup(ja as Dict, 'auto.DashboardAdvancedPage.k1')
    const enLabel = lookup(en as Dict, 'auto.DashboardAdvancedPage.k1')
    expect(jaLabel).toBe('ショット使用時のラリー結果')
    expect(enLabel.toLowerCase()).toContain('rally')
  })
})
