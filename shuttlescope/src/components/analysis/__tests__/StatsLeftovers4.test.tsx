/**
 * 統計規則 R1/R4 の消費側テスト (取りこぼし 4): ダブルス分析と移動量カード。
 *
 * backend が null (データなし) で返す平均ラリー長 / 前衛率 / バランス / 方向内訳を、
 * 画面が 0 や NaN として描かないこと、有効データは従来どおり描くことを固定する。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, configure } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

configure({ asyncUtilTimeout: 8000 })
vi.setConfig({ testTimeout: 30000 })

vi.mock('@/api/client', () => ({
  apiGet: vi.fn(),
  API_BASE_URL: '',
}))

vi.mock('@/components/common/RoleGuard', () => ({
  RoleGuard: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

import * as apiClient from '@/api/client'
import { DoublesAnalysis } from '../DoublesAnalysis'

const mockApi = vi.mocked(apiClient.apiGet)

function mockRoutes(routes: Record<string, unknown>) {
  mockApi.mockImplementation(async (url: string) => {
    if (url in routes) return routes[url] as never
    return { success: true, data: null, meta: {} } as never
  })
}

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}
;(globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = RO

beforeEach(() => {
  mockApi.mockReset()
})

const META = { sample_size: 3, confidence: { level: 'low', stars: '', label: '' } }

describe('DoublesAnalysis: パートナー平均ラリー長', () => {
  const partnerResp = (avg: number | null) => ({
    success: true,
    data: {
      partners: [
        { partner_id: 2, partner_name: 'PARTNER_X', match_count: 1, win_rate: 1, synergy_score: 0.3, avg_rally_length: avg },
      ],
    },
    meta: META,
  })

  it('null は 0.0 でなく — を描く', async () => {
    mockRoutes({ '/analysis/partner_comparison': partnerResp(null) })
    wrap(<DoublesAnalysis playerId={1} allMatches={[]} />)
    await waitFor(() => expect(screen.getByText('PARTNER_X')).toBeTruthy())
    expect(document.body.textContent).not.toContain('0.0')
    expect(document.body.textContent).not.toContain('NaN')
  })

  it('有効値は従来どおり小数 1 桁', async () => {
    mockRoutes({ '/analysis/partner_comparison': partnerResp(5.25) })
    wrap(<DoublesAnalysis playerId={1} allMatches={[]} />)
    await waitFor(() => expect(screen.getByText('PARTNER_X')).toBeTruthy())
    expect(document.body.textContent).toContain('5.3')
  })
})

describe('DoublesAnalysis: コートカバレッジ', () => {
  const matches = [
    { match_id: 7, date: '2026-01-01', opponent: 'OPP', format: 'doubles', result: 'win' },
  ] as never

  it('両者ストローク 0 件 (率 null) はレーダーを描かず NaN を出さない', async () => {
    mockRoutes({
      '/analysis/court_coverage_split': {
        success: true,
        data: {
          balance_score: null,
          player_a: { front_rate: null, back_rate: null, mid_rate: null, total_strokes: 0 },
          partner_a: { front_rate: null, back_rate: null, mid_rate: null, total_strokes: 0 },
        },
        meta: META,
      },
    })
    const { container } = wrap(<DoublesAnalysis playerId={1} allMatches={matches} />)
    await waitFor(() => expect(mockApi.mock.calls.some((c) => c[0] === '/analysis/court_coverage_split')).toBe(true))
    await waitFor(() => expect(container.textContent).not.toContain('読み込み中'))
    await waitFor(() => expect(container.textContent).toContain('コートデータがありません'))
    expect(container.textContent).not.toContain('NaN')
  })

  it('片側のみ null: balance は — 、有効側だけ描く', async () => {
    mockRoutes({
      '/analysis/court_coverage_split': {
        success: true,
        data: {
          balance_score: null,
          player_a: { front_rate: 0.5, back_rate: 0.25, mid_rate: 0.25, total_strokes: 4 },
          partner_a: { front_rate: null, back_rate: null, mid_rate: null, total_strokes: 0 },
        },
        meta: META,
      },
    })
    const { container } = wrap(<DoublesAnalysis playerId={1} allMatches={matches} />)
    await waitFor(() => expect(container.textContent).toContain('4打'))
    expect(container.textContent).not.toContain('0打')
    expect(container.textContent).toContain('—')
    expect(container.textContent).not.toContain('NaN')
  })

  it('有効データのバランススコアは従来どおり百分率の整数', async () => {
    mockRoutes({
      '/analysis/court_coverage_split': {
        success: true,
        data: {
          balance_score: 0.9,
          player_a: { front_rate: 0.5, back_rate: 0.25, mid_rate: 0.25, total_strokes: 4 },
          partner_a: { front_rate: 0.4, back_rate: 0.3, mid_rate: 0.3, total_strokes: 5 },
        },
        meta: META,
      },
    })
    const { container } = wrap(<DoublesAnalysis playerId={1} allMatches={matches} />)
    await waitFor(() => expect(container.textContent).toContain('90'))
  })
})
