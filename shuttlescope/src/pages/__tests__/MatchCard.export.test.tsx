/**
 * 試合カードの .sspkg エクスポート: 生リンクではなく認証付きの取得を通す。
 * 成功時は取得した Blob を保存し、401/403 や失敗時は Blob 化せずエラーを出す。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

const apiGetBlob = vi.fn()
const saveBlobAs = vi.fn()

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ role: 'coach', hasPageAccess: () => true }),
}))
vi.mock('@/api/client', () => ({
  apiGetBlob: (...args: unknown[]) => apiGetBlob(...args),
}))
vi.mock('@/utils/saveBlob', () => ({
  saveBlobAs: (...args: unknown[]) => saveBlobAs(...args),
}))
vi.mock('@/components/analysis/PipelineJobBadge', () => ({ PipelineJobBadge: () => null }))

import { MatchCard } from '@/components/matchList/MatchCard'
import type { Match } from '@/types'

const match = {
  id: 7, tournament: 'T', tournament_level: 'IC', round: 'F', date: '2026-01-01', format: 'singles',
  player_a_id: 1, player_b_id: 2, annotation_status: 'complete', annotation_progress: 1,
  created_at: '', updated_at: '', player_b: { id: 2, name: 'Opponent' },
}
const noop = () => {}

function renderCard() {
  return render(
    <MemoryRouter>
      <MatchCard match={match as unknown as Match} onDownload={noop} onEdit={noop}
        deleteConfirmId={null} onDeleteConfirm={noop} onDeleteExecute={noop} />
    </MemoryRouter>,
  )
}

function exportButton(container: HTMLElement): HTMLElement {
  // 生リンクは廃止した
  expect(container.querySelector('a[href*="export/package"]')).toBeNull()
  const el = container.querySelector('[data-testid="match-export"]')
  if (!el) throw new Error('export button not found')
  return el as HTMLElement
}

beforeEach(() => {
  apiGetBlob.mockReset()
  saveBlobAs.mockReset()
})

describe('MatchCard export', () => {
  it('fetches through the authenticated client and saves the blob', async () => {
    const blob = new Blob(['{}'])
    apiGetBlob.mockResolvedValue({ blob, filename: 'match_x.json' })
    const { container } = renderCard()

    fireEvent.click(exportButton(container))

    await waitFor(() => expect(saveBlobAs).toHaveBeenCalledWith(blob, 'match_x.json'))
    expect(apiGetBlob).toHaveBeenCalledWith('/export/package', { match_id: 7 })
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('shows an error and saves nothing when the server rejects the request', async () => {
    apiGetBlob.mockRejectedValue(Object.assign(new Error('nope'), { status: 401 }))
    const { container } = renderCard()

    fireEvent.click(exportButton(container))

    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy())
    expect(saveBlobAs).not.toHaveBeenCalled()
  })
})
