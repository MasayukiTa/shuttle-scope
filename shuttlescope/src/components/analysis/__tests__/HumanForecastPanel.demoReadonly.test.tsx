/**
 * Item #698: demo ロールでは人間予測フォームを編集可能にしない。
 *
 * backend user_can_access_match は coach/analyst のみ match scope を許可し、
 * demo ロールは human_forecast POST で 404 になる。よって demo では
 * 入力欄を出さず read-only の注記 (prediction.human_forecast_demo_readonly) を出す。
 * coach では従来どおり入力フォーム (保存ボタン) が出る。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { UserRole } from '@/types'

let mockRole: UserRole | null = 'demo'

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ role: mockRole }),
}))

vi.mock('@/api/client', () => ({
  apiGet: vi.fn(async () => ({ success: true, data: { summary: [], match_comparisons: [], total_forecasts: 0 } })),
  apiPost: vi.fn(),
  apiDelete: vi.fn(),
  newIdempotencyKey: () => 'test-key',
}))

import i18n from '@/i18n'
import { HumanForecastPanel } from '../HumanForecastPanel'

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <HumanForecastPanel matchId={1} playerId={2} />
    </QueryClientProvider>,
  )
}

function openForm() {
  fireEvent.click(screen.getByText(i18n.t('prediction.human_forecast_add')))
}

describe('HumanForecastPanel demo read-only (#698)', () => {
  beforeEach(() => { i18n.changeLanguage('ja') })

  it('demo ロールでは read-only 注記を出し、保存ボタンを出さない', () => {
    mockRole = 'demo'
    wrap()
    openForm()
    expect(screen.getByText(i18n.t('prediction.human_forecast_demo_readonly'))).toBeTruthy()
    expect(screen.queryByText(i18n.t('prediction.human_forecast_save'))).toBeNull()
  })

  it('player ロールでも入力フォームを出さない', () => {
    mockRole = 'player'
    wrap()
    openForm()
    expect(screen.getByText(i18n.t('prediction.human_forecast_demo_readonly'))).toBeTruthy()
    expect(screen.queryByText(i18n.t('prediction.human_forecast_save'))).toBeNull()
  })

  it('coach ロールでは保存ボタンを出す', () => {
    mockRole = 'coach'
    wrap()
    openForm()
    expect(screen.getAllByText(i18n.t('prediction.human_forecast_save')).length).toBeGreaterThan(0)
    expect(screen.queryByText(i18n.t('prediction.human_forecast_demo_readonly'))).toBeNull()
  })
})
