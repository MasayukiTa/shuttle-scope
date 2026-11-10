/**
 * #677: 起動時 health check が一定時間 ready にならない半断時に、
 * 無限ローディングではなく「サーバに接続できません / 再読み込み」を明示することを検証する。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import i18n from '@/i18n'

// health は常に false (半断・未起動) を返す。その他 App が import する export は no-op。
const checkHealthMock = vi.fn().mockResolvedValue(false)
vi.mock('@/api/client', () => ({
  checkHealth: () => checkHealthMock(),
  authLogout: vi.fn().mockResolvedValue({ success: true }),
  authMe: vi.fn().mockResolvedValue({ role: 'player', user_id: null, player_id: null, team_name: null, display_name: null, page_access: [] }),
  publicInquiryUnreadCount: vi.fn().mockResolvedValue({ success: true, data: { count: 0 } }),
  getTutorialDemoTarget: vi.fn().mockResolvedValue({ success: true, data: null }),
  apiPost: vi.fn().mockResolvedValue({}),
  API_BASE_URL: 'http://localhost/api',
  getAuthHeaders: () => ({}),
  isDemoMode: () => false,
  setDemoMode: vi.fn(),
}))

import App from '@/App'

describe('App backend-unreachable state (#677)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    checkHealthMock.mockClear()
  })
  afterEach(() => {
    vi.runOnlyPendingTimers()
    vi.useRealTimers()
  })

  it('shows an explicit unreachable + retry state instead of looping forever', async () => {
    render(<App />)

    // health poll を 20s 以上回して elapsed を閾値超えさせる。
    // checkHealth=false → setElapsed → 500ms 待機を繰り返す。
    for (let i = 0; i < 60; i++) {
      await act(async () => {
        await Promise.resolve()
        vi.advanceTimersByTime(500)
        await Promise.resolve()
      })
    }

    const title = i18n.t('app.unreachable_title')
    const retry = i18n.t('app.retry')
    expect(screen.getByText(title)).toBeTruthy()
    expect(screen.getByRole('button', { name: new RegExp(retry) })).toBeTruthy()
  })
})
