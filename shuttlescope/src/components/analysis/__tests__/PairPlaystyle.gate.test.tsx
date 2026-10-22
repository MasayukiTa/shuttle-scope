/**
 * PairPlaystyle: 少標本ではカテゴリ名を確定表示しない (監査 #745)、取得失敗はエラー表示 (#743 周辺)。
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const apiGet = vi.fn()
vi.mock('@/api/client', () => ({ apiGet: (...a: unknown[]) => apiGet(...a) }))

import { PairPlaystyle, isPlaystyleSettled, PLAYSTYLE_MIN_STROKES } from '../PairPlaystyle'

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

function response(sampleSize: number) {
  return {
    success: true,
    data: {
      playstyle: 'FRONT-STYLE-LABEL',
      playstyle_en: 'net_dominant',
      zone_distribution: {},
      metrics: {
        net_zone_rate: 1,
        back_zone_rate: 0,
        mid_zone_rate: 0,
        smash_rate: 0,
        net_shot_rate: 1,
        match_count: 1,
      },
    },
    meta: { sample_size: sampleSize, confidence: { level: 'low', stars: '*', label: 'low' } },
  }
}

describe('PairPlaystyle', () => {
  it('閾値の判定', () => {
    expect(isPlaystyleSettled(1)).toBe(false)
    expect(isPlaystyleSettled(PLAYSTYLE_MIN_STROKES - 1)).toBe(false)
    expect(isPlaystyleSettled(PLAYSTYLE_MIN_STROKES)).toBe(true)
  })

  it('1 打ではカテゴリ名を出さず、判定保留と n を出す', async () => {
    apiGet.mockResolvedValueOnce(response(1))
    render(wrap(<PairPlaystyle playerAId={1} playerBId={2} />))
    expect(await screen.findByText('判定保留')).toBeInTheDocument()
    expect(screen.queryByText('FRONT-STYLE-LABEL')).toBeNull()
  })

  it('十分な打球数ならカテゴリ名を出す', async () => {
    apiGet.mockResolvedValueOnce(response(PLAYSTYLE_MIN_STROKES))
    render(wrap(<PairPlaystyle playerAId={1} playerBId={2} />))
    expect(await screen.findByText('FRONT-STYLE-LABEL')).toBeInTheDocument()
  })

  it('取得失敗は「データなし」ではなくエラー通知', async () => {
    apiGet.mockRejectedValueOnce(new Error('boom'))
    render(wrap(<PairPlaystyle playerAId={1} playerBId={2} />))
    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })
})
