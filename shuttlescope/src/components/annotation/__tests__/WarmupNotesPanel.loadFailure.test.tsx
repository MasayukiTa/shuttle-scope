import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

import { WarmupNotesPanel } from '../WarmupNotesPanel'
import * as apiClient from '@/api/client'

vi.mock('@/api/client', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
}))

const props = {
  matchId: 7,
  playerAId: 1,
  playerBId: 2,
  playerAName: 'A',
  playerBName: 'B',
  locked: false,
  onClose: vi.fn(),
}

describe('WarmupNotesPanel existing-observation load', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('blocks saving and offers a retry when the existing observations fail to load', async () => {
    vi.mocked(apiClient.apiGet).mockRejectedValue(new Error('network'))
    render(<WarmupNotesPanel {...props} />)

    expect(await screen.findByRole('alert')).toHaveTextContent('読み込めませんでした')
    expect(screen.getByRole('button', { name: '再試行' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^保存/ })).toBeDisabled()
  })

  it('allows saving once the load succeeds', async () => {
    vi.mocked(apiClient.apiGet).mockResolvedValue({ success: true, data: [] })
    render(<WarmupNotesPanel {...props} />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^保存/ })).toBeEnabled()
    })
  })
})
