import { describe, it, expect, vi } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

const pipelineJobs = vi.fn()
vi.mock('@/api/client', () => ({
  pipelineJobs: (...args: unknown[]) => pipelineJobs(...args),
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
