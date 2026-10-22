/**
 * チーム管理: メンバー一覧 (/auth/users) の取得失敗を「0 人」として表示しない。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

vi.mock('@/hooks/useAuth', () => ({ useAuth: () => ({ role: 'admin' }) }))
vi.mock('@/hooks/useIsMobile', () => ({ useIsMobile: () => false }))

const listTeams = vi.fn()
const apiGet = vi.fn()
vi.mock('@/api/client', () => ({
  listTeams: (...a: unknown[]) => listTeams(...a),
  apiGet: (...a: unknown[]) => apiGet(...a),
  createTeam: vi.fn(),
  patchTeam: vi.fn(),
  deleteTeam: vi.fn(),
  getTeamDependencies: vi.fn(),
}))

import { TeamManagementPage } from '../TeamManagementPage'

const team = { id: 1, name: 'Team A', display_id: null, short_name: null, notes: null }

describe('TeamManagementPage members fetch failure', () => {
  beforeEach(() => {
    listTeams.mockReset()
    apiGet.mockReset()
    listTeams.mockResolvedValue({ success: true, data: [team] })
  })

  it('shows a dash instead of 0 when the member list request fails', async () => {
    apiGet.mockRejectedValue(new Error('500'))
    const { container } = render(<TeamManagementPage />)
    await waitFor(() => expect(screen.getAllByText('Team A').length).toBeGreaterThan(0))
    const badge = container.querySelector('button span.text-xs')
    expect(badge?.textContent).toBe('—')
  })

  it('treats success:false as a failure too', async () => {
    apiGet.mockResolvedValue({ success: false, data: [] })
    const { container } = render(<TeamManagementPage />)
    await waitFor(() => expect(screen.getAllByText('Team A').length).toBeGreaterThan(0))
    expect(container.querySelector('button span.text-xs')?.textContent).toBe('—')
  })

  it('shows the real count when the request succeeds', async () => {
    apiGet.mockResolvedValue({ success: true, data: [{ id: 9, username: 'u', display_name: null, role: 'player', team_id: 1 }] })
    const { container } = render(<TeamManagementPage />)
    await waitFor(() => expect(container.querySelector('button span.text-xs')?.textContent).toBe('1'))
  })
})
