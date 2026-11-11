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
  sessionPassword: 'pw-1234',
  onClose: vi.fn(),
}

const mockedApiPost = vi.mocked(apiPost)

describe('SessionShareModal end session', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('ends the session and notifies the parent when confirmed', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    mockedApiPost.mockResolvedValueOnce({ success: true } as never)
    const onEnded = vi.fn()
    const onClose = vi.fn()
    render(<SessionShareModal {...baseProps} onEnded={onEnded} onClose={onClose} />)

    fireEvent.click(screen.getByRole('button', { name: 'セッションを終了' }))

    await waitFor(() => expect(mockedApiPost).toHaveBeenCalledWith('/sessions/ABC123/end', {}))
    await waitFor(() => expect(onEnded).toHaveBeenCalledTimes(1))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('does nothing when the confirm dialog is dismissed', () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    const onEnded = vi.fn()
    render(<SessionShareModal {...baseProps} onEnded={onEnded} />)

    fireEvent.click(screen.getByRole('button', { name: 'セッションを終了' }))

    expect(mockedApiPost).not.toHaveBeenCalled()
    expect(onEnded).not.toHaveBeenCalled()
  })

  it('shows an error and keeps the session when the request fails', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    mockedApiPost.mockRejectedValueOnce(new Error('network'))
    const onEnded = vi.fn()
    render(<SessionShareModal {...baseProps} onEnded={onEnded} />)

    fireEvent.click(screen.getByRole('button', { name: 'セッションを終了' }))

    expect(await screen.findByText(/セッションを終了できませんでした/)).toBeInTheDocument()
    expect(onEnded).not.toHaveBeenCalled()
  })
})
