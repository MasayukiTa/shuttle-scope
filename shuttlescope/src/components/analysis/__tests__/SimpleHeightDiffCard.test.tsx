/**
 * 簡易分析「打球の高さ差」(要望8 / SD-08) の最小表示を固定する。
 *
 * - 見出し・説明が t() 経由で出る（英語 UI で日本語が残らない）
 * - pairs>0 のとき 平均 / 内訳（差0〜3）が出る
 * - pairs===0 のとき no_data 文言が出る
 * - 使う i18n キーが ja / en 両方に存在する
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import ja from '@/i18n/ja.json'
import en from '@/i18n/en.json'

type Dict = Record<string, unknown>
function lookup(dict: Dict, key: string, vars?: Record<string, unknown>): string {
  const v = key.split('.').reduce<unknown>((o, k) => (o as Dict | undefined)?.[k], dict)
  let s = typeof v === 'string' ? v : key
  if (vars) {
    for (const [k, val] of Object.entries(vars)) {
      s = s.replace(new RegExp(`\\{\\{\\s*${k}\\s*\\}\\}`, 'g'), String(val))
    }
  }
  return s
}

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, vars?: Record<string, unknown>) => lookup(en as Dict, key, vars),
  }),
}))

vi.mock('@/api/simpleHeightDiff', () => ({
  fetchSimpleHeightDiff: vi.fn(),
}))

import * as api from '@/api/simpleHeightDiff'
import { SimpleHeightDiffCard } from '../SimpleHeightDiffCard'

const mockFetch = vi.mocked(api.fetchSimpleHeightDiff)

beforeEach(() => {
  mockFetch.mockReset()
})

describe('SimpleHeightDiffCard (SD-08)', () => {
  it('pairs>0 で平均と内訳を t() 経由（英語）で表示する', async () => {
    mockFetch.mockResolvedValue({
      success: true,
      data: {
        match_id: 1,
        pairs: 2,
        mean_diff: 1.0,
        distribution: { '0': 1, '1': 0, '2': 1, '3': 0 },
      },
    } as never)

    const { container } = render(<SimpleHeightDiffCard matchId={1} />)
    await waitFor(() =>
      expect(container.textContent).toContain('Shot-height difference (simple analysis)'),
    )
    // 平均 1.00 と 内訳見出しが出る
    expect(container.textContent).toContain('1.00')
    expect(container.textContent).toContain('Difference breakdown')
    // 日本語が英語 UI に残らない
    expect(container.textContent).not.toContain('打球の高さ差')
  })

  it('pairs===0 で no_data 文言を出す', async () => {
    mockFetch.mockResolvedValue({
      success: true,
      data: {
        match_id: 1,
        pairs: 0,
        mean_diff: null,
        distribution: { '0': 0, '1': 0, '2': 0, '3': 0 },
      },
    } as never)

    const { container } = render(<SimpleHeightDiffCard matchId={1} />)
    await waitFor(() =>
      expect(container.textContent).toContain('No returns with an entered shot height yet.'),
    )
  })

  it('取得失敗で error 文言を出す', async () => {
    mockFetch.mockRejectedValue(new Error('boom'))
    const { container } = render(<SimpleHeightDiffCard matchId={1} />)
    await waitFor(() =>
      expect(container.textContent).toContain('Could not load the simple analysis.'),
    )
  })

  it('使用 i18n キーが ja / en 両方に存在する', () => {
    const keys = [
      'simple_analysis.height_diff_title',
      'simple_analysis.height_diff_desc',
      'simple_analysis.pairs',
      'simple_analysis.mean_diff',
      'simple_analysis.distribution',
      'simple_analysis.diff_bucket',
      'simple_analysis.no_data',
      'simple_analysis.error',
    ]
    for (const dict of [ja, en] as Dict[]) {
      for (const k of keys) {
        expect(lookup(dict, k)).not.toBe(k)
      }
    }
  })
})
