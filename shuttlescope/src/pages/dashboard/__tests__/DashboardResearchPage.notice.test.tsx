/**
 * 研究タブ: 「研究段階・参考情報」注意バナーはページ先頭に 1 回だけ。
 * カードごとに繰り返さない。研究タブ以外でカードを使う場合は各カードが自前で表示する。
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { UserRole } from '@/types'
import ja from '@/i18n/ja.json'

let mockRole: UserRole | null = 'analyst'

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    role: mockRole,
    hasRole: (allowed: UserRole[]) => (!mockRole ? false : mockRole === 'admin' ? true : allowed.includes(mockRole)),
  }),
}))
vi.mock('@/api/client', () => ({
  API_BASE_URL: 'http://x',
  apiGet: vi.fn(async () => ({ success: true, data: [], meta: {} })),
  apiPost: vi.fn(async () => ({ success: true, data: {} })),
}))
vi.mock('@/components/dashboard/advice_chat/AdviceChatPanel', () => ({ AdviceChatPanel: () => null }))

import { DashboardResearchPage } from '../DashboardResearchPage'
import { ResearchNotice } from '@/components/dashboard/ResearchNotice'
import { StateEPVCard } from '@/components/analysis/StateEPVCard'

const HEADING: string = (ja as any).auto.ResearchNotice.heading
const filters: any = {}

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('ResearchNotice repetition', () => {
  it('research tab shows the warning banner exactly once (analyst)', async () => {
    mockRole = 'analyst'
    wrap(<DashboardResearchPage playerId={1} filters={filters} />)
    // カードが描画されるのを待つ (StateEPVCard の見出し)
    await waitFor(() => expect(screen.getAllByText((ja as any).auto.StateEPVCard.k1).length).toBeGreaterThan(0))
    expect(screen.getAllByText(HEADING)).toHaveLength(1)
    expect(document.querySelectorAll('[data-tutorial="dashboard.researchNotice"]')).toHaveLength(1)
  })

  it('research tab keeps each card own assumptions and promotion criteria, without a second heading', async () => {
    mockRole = 'analyst'
    wrap(<DashboardResearchPage playerId={1} filters={filters} />)
    await waitFor(() => expect(screen.getAllByText((ja as any).auto.StateEPVCard.k1).length).toBeGreaterThan(0))
    // StateEPVCard の昇格条件 (カード固有) は見出しなしで残る
    expect(screen.getAllByText(/状態ごとN≥50/).length).toBeGreaterThan(0)
    // 共通警告の見出しは 1 回のまま
    expect(screen.getAllByText(HEADING)).toHaveLength(1)
    // カード間で前提が違うこと・ラリーが試合内でまとまることを 1 回だけ示す
    expect(screen.getAllByTestId('research-dependence-note')).toHaveLength(1)
    // 絞り込みが効かないカードには、その旨を 1 行で示す
    expect(screen.getAllByTestId('unfiltered-scope-note').length).toBeGreaterThan(0)
  })

  it('card used outside the research tab keeps its own warning', async () => {
    mockRole = 'analyst'
    wrap(<StateEPVCard playerId={1} filters={filters} />)
    await waitFor(() => expect(screen.getAllByText(HEADING)).toHaveLength(1))
  })

  it('ResearchNotice renders by default and is silent only inside the research scope', () => {
    wrap(<ResearchNotice caution="c" />)
    expect(screen.getAllByText(HEADING)).toHaveLength(1)
  })

  it('player never sees research-tier cards (role gating unchanged)', async () => {
    mockRole = 'player'
    wrap(<DashboardResearchPage playerId={1} filters={filters} />)
    await waitFor(() => expect(screen.getAllByText(HEADING).length).toBe(1))
    expect(screen.queryByText((ja as any).auto.StateEPVCard.k1)).toBeNull()
  })
})
