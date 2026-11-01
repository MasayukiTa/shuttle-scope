/**
 * 監査#750 / #751: /conditions 系 API の実レスポンス形状と
 * frontend フックの整合を固定する。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

const calls: unknown[][] = []
let handler: () => Promise<unknown> = async () => ({ success: true, data: {} })
vi.mock('@/api/client', () => ({
  apiGet: async (...a: unknown[]) => {
    calls.push(a)
    return handler()
  },
}))
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ role: 'coach' }),
}))

import { useDiscrepancy, useInsights } from '../useConditionAnalytics'

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

describe('useDiscrepancy (監査#751)', () => {
  beforeEach(() => {
    calls.length = 0
  })

  it('{success,data:{items,n}} を unwrap し flags を 1 行ずつ平坦化する', async () => {
    handler = async () => ({
      success: true,
      data: {
        items: [
          {
            condition_id: 7,
            measured_at: '2026-04-01',
            flags: [
              { type: 'ecw_spike', severity: 'high' },
              { type: 'mood_gap', severity: 'medium' },
            ],
          },
        ],
        n: 1,
      },
    })
    const { result } = renderHook(() => useDiscrepancy(7), { wrapper })
    await waitFor(() => expect(result.current.data).toBeDefined())
    const items = result.current.data!
    expect(items).toHaveLength(2)
    expect(items[0]).toEqual({
      condition_id: 7,
      date: '2026-04-01',
      type: 'ecw_spike',
      severity: 'high',
      detail: null,
    })
    expect(items[1].type).toBe('mood_gap')
    expect(items[1].date).toBe('2026-04-01')
  })

  it('data が配列でなくても (旧バグの形) 空配列になる', async () => {
    handler = async () => ({ success: true, data: { items: [], n: 0 } })
    const { result } = renderHook(() => useDiscrepancy(7), { wrapper })
    await waitFor(() => expect(result.current.data).toBeDefined())
    expect(result.current.data).toEqual([])
  })
})

describe('useInsights (監査#750)', () => {
  beforeEach(() => {
    calls.length = 0
  })

  it('raw_factor_trends 辞書と validity_summary counts/n をそのまま受ける', async () => {
    handler = async () => ({
      success: true,
      data: {
        growth_cards: [],
        validity_summary: { counts: { ok: 4, caution: 1, unreliable: 0 }, n: 5 },
        raw_factor_trends: {
          f1_physical: [{ measured_at: '2026-04-01', value: 12 }],
          f5_sleep_life: [{ measured_at: '2026-04-01', value: 3 }],
        },
      },
    })
    const { result } = renderHook(() => useInsights(11), { wrapper })
    await waitFor(() => expect(result.current.data).toBeDefined())
    const d = result.current.data!
    expect(d.validity_summary?.counts?.ok).toBe(4)
    expect(d.validity_summary?.n).toBe(5)
    expect(Object.keys(d.raw_factor_trends ?? {})).toEqual(['f1_physical', 'f5_sleep_life'])
    expect(d.raw_factor_trends?.f1_physical[0]).toEqual({ measured_at: '2026-04-01', value: 12 })
  })
})
