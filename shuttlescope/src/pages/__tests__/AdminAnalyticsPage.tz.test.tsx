import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import AdminAnalyticsPage from '@/pages/AdminAnalyticsPage'

// Audit #77: aggregate timestamps may arrive as timezone-naive UTC strings.
// A naive string and its explicit-Z form must render to the same local time,
// proving the component treats zoneless values as UTC (not local).

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (key === 'admin.analytics.stat_as_of') return 'as_of'
      if (opts && 'time' in opts) return `last:${opts.time as string}`
      return key
    },
  }),
}))

vi.mock('@/components/common/MIcon', () => ({ MIcon: () => null }))

const mockGet = vi.fn()
vi.mock('@/api/client', () => ({ apiGet: (url: string) => mockGet(url) }))

function overview(asOf: string) {
  return {
    wau: 0, mau: 0, total_events_7d: 0,
    wau_by_role: {}, wau_by_platform: {},
    total_events_all: 0, last_event_at: null,
    as_of: asOf,
  }
}

function wire(asOf: string) {
  mockGet.mockImplementation((url: string) => {
    if (url === '/admin/analytics/overview') return Promise.resolve({ data: overview(asOf) })
    return Promise.resolve({ data: { items: [], series: {}, funnel: {}, abandonment_last_input_top: [], days: 30 } })
  })
}

async function renderAsOf(asOf: string): Promise<string> {
  wire(asOf)
  render(<AdminAnalyticsPage />)
  const el = await screen.findByText('as_of')
  const stat = el.parentElement as HTMLElement
  return stat.textContent ?? ''
}

describe('AdminAnalyticsPage as_of timezone normalization (audit #77)', () => {
  it('treats a zoneless timestamp as UTC: naive and explicit-Z render identically', async () => {
    const naive = await renderAsOf('2026-10-21T11:51:32')
    const withZ = await renderAsOf('2026-10-21T11:51:32Z')
    expect(naive).toBe(withZ)
    expect(naive).not.toMatch(/Invalid Date/)
  })

  it('keeps an explicit offset as-is (does not append Z)', async () => {
    const off = await renderAsOf('2026-10-21T20:51:32+09:00')
    const z = await renderAsOf('2026-10-21T11:51:32Z')
    expect(off).toBe(z)
  })
})
