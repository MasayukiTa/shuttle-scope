/**
 * チーム管理: 行操作ボタンの aria-label に対象チーム名を含める (項目512)。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import ja from '@/i18n/ja.json'

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

const tm = (ja as unknown as { auto: { TeamManagementPage: Record<string, string> } }).auto.TeamManagementPage
const team = { id: 1, name: 'Team A', display_id: null, short_name: null, notes: null }

describe('TeamManagementPage row action aria-labels (項目512)', () => {
  beforeEach(() => {
    listTeams.mockReset(); apiGet.mockReset()
    listTeams.mockResolvedValue({ success: true, data: [team] })
    apiGet.mockResolvedValue({ success: true, data: [] })
  })

  it('edit / delete / members buttons expose the team name', async () => {
    render(<TeamManagementPage />)
    await waitFor(() => expect(screen.getAllByText('Team A').length).toBeGreaterThan(0))
    expect(screen.getByLabelText(tm.aria_edit.replace('{{name}}', 'Team A'))).toBeTruthy()
    expect(screen.getByLabelText(tm.aria_delete.replace('{{name}}', 'Team A'))).toBeTruthy()
    expect(screen.getByLabelText(tm.aria_members.replace('{{name}}', 'Team A'))).toBeTruthy()
  })
})
