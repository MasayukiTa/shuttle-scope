import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

const pipelineJobs = vi.fn()
vi.mock('@/api/client', () => ({
  pipelineJobs: (...args: unknown[]) => pipelineJobs(...args),
}))

let mockRole: string | null = 'analyst'
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ role: mockRole }),
}))

import { PipelineJobBadge } from '../PipelineJobBadge'

function renderBadge() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <PipelineJobBadge matchId={1} />
    </QueryClientProvider>,
  )
}

describe('PipelineJobBadge', () => {
  beforeEach(() => {
    mockRole = 'analyst'
    pipelineJobs.mockReset()
  })

  it('renders nothing and does not fetch for roles the backend answers with an empty list', async () => {
    mockRole = 'admin'
    const { container } = renderBadge()
    await new Promise((r) => setTimeout(r, 20))
    expect(container.textContent).toBe('')
    expect(pipelineJobs).not.toHaveBeenCalled()
  })

  it('shows "unknown", not "none", when the job list cannot be fetched', async () => {
    pipelineJobs.mockRejectedValueOnce(new Error('500'))
    const { container } = renderBadge()
    await waitFor(() => expect(container.textContent).toBe('pipeline.status.unknown'))
  })

  it('shows "none" when the list loaded and has no job for the match', async () => {
    pipelineJobs.mockResolvedValueOnce([{ match_id: 2, status: 'done' }])
    const { container } = renderBadge()
    await waitFor(() => expect(container.textContent).toBe('pipeline.status.none'))
  })
})
