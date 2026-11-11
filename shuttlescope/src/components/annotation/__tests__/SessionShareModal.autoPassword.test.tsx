import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

import { SessionShareModal } from '../SessionShareModal'
import { apiPost } from '@/api/client'

vi.mock('@/api/client', () => ({
  apiPost: vi.fn(),
}))
// jsdom has no canvas; QR generation rejects. Irrelevant to these tests.
vi.mock('qrcode', () => ({
  default: { toCanvas: vi.fn(() => Promise.reject(new Error('no canvas'))) },
}))

const baseProps = {
  sessionCode: 'ABC123',
  coachUrls: ['http://192.168.0.5:5173/#/annotator/1'],
  cameraSenderUrls: ['http://192.168.0.5:5173/#/camera/ABC123'],
  viewerUrls: ['http://192.168.0.5:5173/#/viewer/ABC123'],
  onClose: vi.fn(),
}

const mockedApiPost = vi.mocked(apiPost)

describe('SessionShareModal auto-generates a share password for legacy sessions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('auto-generates and shows a masked password when the session has none (hasPassword=false)', async () => {
    mockedApiPost.mockResolvedValueOnce({
      success: true,
      data: { session_password: 'auto-pass-99' },
    } as never)

    render(<SessionShareModal {...baseProps} hasPassword={false} />)

    // The modal must request a generated password exactly once on open,
    // reusing the existing regenerate endpoint (same strength generator).
    await waitFor(() =>
      expect(mockedApiPost).toHaveBeenCalledWith('/sessions/ABC123/regenerate-password', {}),
    )

    // Password is shown masked by default (never the literal 未設定),
    // and the eye toggle reveals the generated plaintext.
    expect(screen.queryByText('未設定')).not.toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('••••••••')).toBeInTheDocument())
    expect(screen.queryByText('auto-pass-99')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '表示' }))
    expect(await screen.findByText('auto-pass-99')).toBeInTheDocument()
  })

  it('does not auto-generate when the session already has a password (hasPassword=true)', async () => {
    render(<SessionShareModal {...baseProps} hasPassword={true} />)
    // Give any stray effect a tick; the regenerate endpoint must not be called.
    await Promise.resolve()
    expect(mockedApiPost).not.toHaveBeenCalledWith(
      '/sessions/ABC123/regenerate-password',
      {},
    )
    expect(screen.queryByText('未設定')).not.toBeInTheDocument()
  })

  it('does not auto-generate when a plaintext password was already returned on create', async () => {
    render(<SessionShareModal {...baseProps} sessionPassword="created-pw" hasPassword={false} />)
    await Promise.resolve()
    expect(mockedApiPost).not.toHaveBeenCalledWith(
      '/sessions/ABC123/regenerate-password',
      {},
    )
    expect(screen.getByText('••••••••')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '表示' }))
    expect(await screen.findByText('created-pw')).toBeInTheDocument()
  })
})
