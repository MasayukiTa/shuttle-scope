/**
 * #604: Expert Labeler は clips / labels 取得失敗を「クリップなし / 全件未ラベル」に
 * すり替えてはならない。clips 取得が失敗したら、専用のエラー表示 (retry 付き) を出し、
 * 通常の「クリップがありません (no_clips)」空状態には入らないことを検証する。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

const apiGet = vi.fn()
vi.mock('@/api/client', () => ({
  apiGet: (...a: unknown[]) => apiGet(...a),
  apiPost: (...a: unknown[]) => Promise.resolve({}),
}))

// t はキーをそのまま返す (文言に依存せずキーで検証する)。
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k, i18n: { language: 'ja' } }),
}))
vi.mock('@/hooks/useAuth', () => ({ useAuth: () => ({ role: 'analyst' }) }))
vi.mock('@/hooks/useTheme', () => ({ useTheme: () => {} }))
vi.mock('react-router-dom', async (orig) => {
  const actual = await (orig as () => Promise<Record<string, unknown>>)()
  return { ...actual, useParams: () => ({ matchId: '1' }) }
})

import { ExpertLabelerAnnotatePage } from '../ExpertLabelerAnnotatePage'

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ExpertLabelerAnnotatePage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ExpertLabelerAnnotatePage #604 clips load failure', () => {
  beforeEach(() => { apiGet.mockReset() })

  it('clips 取得失敗時は clips_load_failed を alert 表示し、no_clips には入らない', async () => {
    apiGet.mockImplementation((path: string) => {
      if (path === '/v1/expert/clips') return Promise.reject(new Error('500'))
      if (path === '/v1/expert/labels') return Promise.resolve({ labels: [] })
      return Promise.resolve([])
    })
    renderPage()
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('expert_labeler.clips_load_failed')
    expect(screen.getByRole('button', { name: 'expert_labeler.retry' })).toBeTruthy()
    // 失敗を空状態 (no_clips) にすり替えていないこと
    expect(screen.queryByText('expert_labeler.no_clips')).toBeNull()
  })

  it('clips 取得成功で 0 件なら no_clips を表示する (本当の空状態)', async () => {
    apiGet.mockImplementation((path: string) => {
      if (path === '/v1/expert/clips') return Promise.resolve({ clips: [] })
      if (path === '/v1/expert/labels') return Promise.resolve({ labels: [] })
      return Promise.resolve([])
    })
    renderPage()
    await waitFor(() => expect(screen.getByText('expert_labeler.no_clips')).toBeTruthy())
    expect(screen.queryByText('expert_labeler.clips_load_failed')).toBeNull()
  })
})
