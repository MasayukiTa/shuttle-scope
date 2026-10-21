/**
 * AdviceStrip: 「根拠」は読める一覧で出す。生 JSON・内部 source 名は出さない。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

vi.mock('@/api/client', () => ({
  apiGet: vi.fn(),
}))

import * as apiClient from '@/api/client'
import { AdviceStrip } from '../AdviceStrip'

const mockApi = vi.mocked(apiClient.apiGet)

beforeEach(() => {
  mockApi.mockReset()
})

describe('AdviceStrip basis', () => {
  it('renders known fields with display names and hides raw JSON and internal source names', async () => {
    mockApi.mockResolvedValue({
      success: true,
      status: 'ok',
      advice: {
        text: 'ラリー勝率は 55.0% です。',
        confidence: 'medium',
        severity: 'info',
        basis: {
          source: 'head_to_head_wilson_ci',
          match_count: 4,
          rally_count: 120,
          period: '2026-09-01 ~ 2026-09-30',
          some_unknown_field: 'internal_value',
        },
      },
    } as never)

    const { container } = render(<AdviceStrip context="prediction.tab" playerId={1} opponentId={2} />)
    await waitFor(() => expect(screen.getByText('ラリー勝率は 55.0% です。')).toBeTruthy())
    fireEvent.click(screen.getByText('ⓘ 根拠'))

    const text = container.textContent ?? ''
    expect(text).not.toContain('head_to_head_wilson_ci')
    expect(text).not.toContain('some_unknown_field')
    expect(text).not.toContain('internal_value')
    expect(text).not.toContain('{')
    expect(container.querySelector('pre')).toBeNull()
    expect(text).toContain('期間: 2026-09-01 ~ 2026-09-30')
    expect(text).toContain('試合 4')
    expect(text).toContain('ラリー 120')
  })
})
