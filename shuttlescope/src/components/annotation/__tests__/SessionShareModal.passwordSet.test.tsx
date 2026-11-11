import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

import { SessionShareModal } from '../SessionShareModal'
import { apiPost } from '@/api/client'
import ja from '@/i18n/ja.json'

vi.mock('@/api/client', () => ({
  apiPost: vi.fn(),
}))
// jsdom has no canvas; make QR generation resolve to a no-op.
vi.mock('qrcode', () => ({
  default: { toCanvas: vi.fn(() => Promise.resolve()) },
}))

// Pull the exact UI strings from the dictionary so the test has no
// hand-typed multibyte literals (which can corrupt on write).
const L = (ja as { lan_session: Record<string, string> }).lan_session
const SET_LABEL = L.share_modal_password_set
const UNSET_LABEL = L.share_modal_password_unset
const REGEN_WARNING = L.share_modal_password_regenerated_warning
const REGEN_BTN = L.password_regenerate

const baseProps = {
  sessionCode: 'ABC123',
  coachUrls: ['http://192.168.0.5:5173/#/annotator/1'],
  cameraSenderUrls: ['http://192.168.0.5:5173/#/camera/ABC123'],
  viewerUrls: ['http://192.168.0.5:5173/#/viewer/ABC123'],
  onClose: vi.fn(),
}

describe('SessionShareModal password-set flag', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows the set label (not the unset label) when passwordSet is true and no plaintext', () => {
    render(<SessionShareModal {...baseProps} passwordSet={true} />)
    expect(screen.getByText(SET_LABEL)).toBeInTheDocument()
    expect(screen.queryByText(UNSET_LABEL)).not.toBeInTheDocument()
  })

  it('shows the unset label when passwordSet is false and no plaintext', () => {
    render(<SessionShareModal {...baseProps} passwordSet={false} />)
    expect(screen.getByText(UNSET_LABEL)).toBeInTheDocument()
  })

  it('after a successful regenerate, shows the new password and the cannot-be-shown-again warning', async () => {
    vi.mocked(apiPost).mockResolvedValueOnce({
      success: true,
      data: { session_password: 'NewPass42' },
    })
    render(<SessionShareModal {...baseProps} passwordSet={true} />)
    fireEvent.click(screen.getByRole('button', { name: REGEN_BTN }))
    await waitFor(() => expect(screen.getByText('NewPass42')).toBeInTheDocument())
    const alerts = screen.getAllByRole('alert')
    expect(alerts.some((el) => (el.textContent || '').includes(REGEN_WARNING))).toBe(true)
  })
})
