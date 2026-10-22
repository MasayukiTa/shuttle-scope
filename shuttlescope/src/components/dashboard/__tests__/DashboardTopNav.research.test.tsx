/**
 * 「研究」タブは backend の研究 API が admin / analyst 専用なので、
 * それ以外のロールには表示しない (監査 #691)。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import type { UserRole } from '@/types'
import { canViewResearch } from '@/utils/researchAccess'

let mockRole: UserRole | null = 'admin'

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ role: mockRole }),
}))
vi.mock('@/hooks/useTheme', () => ({ useTheme: () => ({ theme: 'light' }) }))
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

import { DashboardTopNav } from '../DashboardTopNav'

function hrefs(): string[] {
  const { container } = render(
    <MemoryRouter initialEntries={['/dashboard/overview']}>
      <DashboardTopNav />
    </MemoryRouter>,
  )
  return Array.from(container.querySelectorAll('a')).map((a) => a.getAttribute('href') ?? '')
}

describe('DashboardTopNav research tab', () => {
  beforeEach(() => { mockRole = 'admin' })

  it.each(['admin', 'analyst'] as UserRole[])('%s: shows the research tab', (r) => {
    mockRole = r
    expect(hrefs()).toContain('/dashboard/research')
  })

  it.each(['coach', 'demo', 'llm', 'player'] as UserRole[])('%s: hides the research tab', (r) => {
    mockRole = r
    expect(hrefs()).not.toContain('/dashboard/research')
  })

  it('coach keeps the other non-player tabs', () => {
    mockRole = 'coach'
    expect(hrefs()).toEqual([
      '/dashboard/overview',
      '/dashboard/live',
      '/dashboard/review',
      '/dashboard/growth',
      '/dashboard/advanced',
    ])
  })
})

describe('canViewResearch', () => {
  it('matches the backend require_admin_or_analyst rule', () => {
    expect(canViewResearch('admin')).toBe(true)
    expect(canViewResearch('analyst')).toBe(true)
    for (const r of ['coach', 'player', 'demo', 'llm', null, undefined, '']) {
      expect(canViewResearch(r)).toBe(false)
    }
  })
})
