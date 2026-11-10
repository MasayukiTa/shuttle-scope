/**
 * 監査#194: ロールバッジの表示名は i18n 経由で出す。
 * 旧実装は ROLE_LABELS に `管理者` 等をハードコードしており、
 * English に切替えてもロールが日本語のまま残っていた。
 * t('roles.' + role) へ移行したので、ja で `管理者` / en で `Admin` になることを固定する。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { UserRole } from '@/types'
import ja from '@/i18n/ja.json'
import en from '@/i18n/en.json'

type Dict = Record<string, unknown>
function lookup(dict: Dict, key: string, fallback?: string): string {
  const v = key.split('.').reduce<unknown>((o, k) => (o as Dict | undefined)?.[k], dict)
  return typeof v === 'string' ? v : (fallback ?? key)
}
function interp(s: string, o?: Record<string, unknown>): string {
  return s.replace(/\{\{(\w+)\}\}/g, (_m, k) => String(o?.[k] ?? ''))
}

let activeDict: Dict = ja as Dict

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string, o?: Record<string, unknown>) =>
      interp(lookup(activeDict, key, typeof fallback === 'string' ? fallback : undefined), o),
  }),
}))

let mockRole: UserRole | null = 'admin'
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    role: mockRole,
    hasRole: (allowed: UserRole[]) =>
      !mockRole ? false : mockRole === 'admin' ? true : allowed.includes(mockRole),
  }),
}))
vi.mock('@/api/client', () => ({
  API_BASE_URL: 'http://x',
  apiGet: vi.fn(async () => ({ success: true, data: [] })),
}))
vi.mock('@/components/dashboard/DashboardTopNav', () => ({ DashboardTopNav: () => null }))
vi.mock('@/components/common/AdviceStrip', () => ({ AdviceStrip: () => null }))
vi.mock('@/components/tutorial/useTutorial', () => ({ useAutoTutorial: () => {} }))
vi.mock('@/components/common/DateRangeSlider', () => ({ DateRangeSlider: () => null }))
vi.mock('../DashboardOverviewPage', () => ({ DashboardOverviewPage: () => null }))
vi.mock('../DashboardLivePage', () => ({ DashboardLivePage: () => null }))
vi.mock('../DashboardReviewPage', () => ({ DashboardReviewPage: () => null }))
vi.mock('../DashboardGrowthPage', () => ({ DashboardGrowthPage: () => null }))
vi.mock('../DashboardAdvancedPage', () => ({ DashboardAdvancedPage: () => null }))
vi.mock('../DashboardResearchPage', () => ({ DashboardResearchPage: () => null }))

import { DashboardShell } from '../DashboardShell'

Element.prototype.scrollIntoView = () => {}

async function renderShell() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const utils = render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/dashboard/overview']}>
        <Routes>
          <Route path="/dashboard/*" element={<DashboardShell />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  await waitFor(() => expect(utils.container.querySelector('h1')).not.toBeNull())
  return utils
}

describe('DashboardShell ロールバッジの i18n (監査#194)', () => {
  beforeEach(() => { mockRole = 'admin'; activeDict = ja as Dict })

  it('ja: admin ロールは roles.admin = 管理者 で表示される', async () => {
    activeDict = ja as Dict
    const { container } = await renderShell()
    expect(lookup(ja as Dict, 'roles.admin')).toBe('管理者')
    await waitFor(() => expect(container.textContent).toContain('管理者'))
  })

  it('en: admin ロールは roles.admin = Admin にローカライズされ日本語が残らない', async () => {
    activeDict = en as Dict
    const { container } = await renderShell()
    expect(lookup(en as Dict, 'roles.admin')).toBe('Admin')
    await waitFor(() => expect(container.textContent).toContain('Admin'))
    expect(container.textContent).not.toContain('管理者')
  })

  it('coach ロールも i18n 経由 (en = Coach)', async () => {
    mockRole = 'coach'
    activeDict = en as Dict
    const { container } = await renderShell()
    await waitFor(() => expect(container.textContent).toContain('Coach'))
    expect(container.textContent).not.toContain('コーチ')
  })
})
