/**
 * チーム管理: coach の編集保存が display_id を PATCH に含めない (項目501)
 *
 * backend PATCH /auth/teams/{id} は body に display_id が含まれるだけで
 * non-admin を 403 にする。coach は name / short_name / notes のみ編集できるため、
 * payload から display_id を除外し、許可された編集が 403 で失敗しないことを検証する。
 * admin では従来どおり display_id を含む。
 *
 * test-setup.ts は i18n を ja で init するため t(key) は翻訳文字列を返す。
 * そのため aria-label の期待値は ja.json から引く (文字列ハードコードを避ける)。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import ja from '@/i18n/ja.json'

const tmLabels = (ja as unknown as { auto: { TeamManagementPage: Record<string, string> } }).auto.TeamManagementPage
// edit button now carries a team-named aria-label (item 512)
const editLabel = tmLabels.aria_edit.replace('{{name}}', 'Team A')
const saveLabel = tmLabels.aria_save.replace('{{name}}', 'Team A')

let mockRole: 'admin' | 'coach' = 'coach'
vi.mock('@/hooks/useAuth', () => ({ useAuth: () => ({ role: mockRole, teamName: 'チームA' }) }))
vi.mock('@/hooks/useIsMobile', () => ({ useIsMobile: () => true }))

const listTeams = vi.fn()
const apiGet = vi.fn()
const patchTeam = vi.fn()
vi.mock('@/api/client', () => ({
  listTeams: (...a: unknown[]) => listTeams(...a),
  apiGet: (...a: unknown[]) => apiGet(...a),
  patchTeam: (...a: unknown[]) => patchTeam(...a),
  createTeam: vi.fn(),
  deleteTeam: vi.fn(),
  getTeamDependencies: vi.fn(),
}))

import { TeamManagementPage } from '../TeamManagementPage'

const team = { id: 1, name: 'Team A', display_id: 'DISP-1', short_name: null, notes: null }

async function openEditAndSave() {
  render(<TeamManagementPage />)
  await waitFor(() => expect(screen.getAllByText('Team A').length).toBeGreaterThan(0))
  fireEvent.click(screen.getByLabelText(editLabel))
  fireEvent.click(screen.getByLabelText(saveLabel))
  await waitFor(() => expect(patchTeam).toHaveBeenCalledTimes(1))
}

describe('TeamManagementPage coach PATCH payload (項目501)', () => {
  beforeEach(() => {
    listTeams.mockReset()
    apiGet.mockReset()
    patchTeam.mockReset()
    listTeams.mockResolvedValue({ success: true, data: [team] })
    apiGet.mockResolvedValue({ success: true, data: [] })
    patchTeam.mockResolvedValue({ success: true, data: team })
  })

  it('coach: display_id を PATCH payload に含めない', async () => {
    mockRole = 'coach'
    await openEditAndSave()
    const payload = patchTeam.mock.calls[0][1] as Record<string, unknown>
    expect(Object.prototype.hasOwnProperty.call(payload, 'display_id')).toBe(false)
  })

  it('admin: display_id を PATCH payload に含む', async () => {
    mockRole = 'admin'
    await openEditAndSave()
    const payload = patchTeam.mock.calls[0][1] as Record<string, unknown>
    expect(Object.prototype.hasOwnProperty.call(payload, 'display_id')).toBe(true)
  })
})
