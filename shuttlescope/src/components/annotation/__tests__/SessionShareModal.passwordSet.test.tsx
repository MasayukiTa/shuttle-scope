import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

import { SessionShareModal } from '../SessionShareModal'
import { apiPost } from '@/api/client'

vi.mock('@/api/client', () => ({
  apiPost: vi.fn(),
}))
// jsdom ã«ã¯ canvas ãç¡ãã®ã§ QR çæã¯ã¢ãã¯ãã
vi.mock('qrcode', () => ({
  default: { toCanvas: vi.fn(() => Promise.resolve()) },
}))

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

  it('å¹³æãç¡ãã¦ã passwordSet ãçãªããè¨­å®æ¸ã¿ããåºããæªè¨­å®ããåºããªã', () => {
    render(<SessionShareModal {...baseProps} passwordSet={true} />)
    expect(screen.getByText(/è¨­å®æ¸ã¿/)).toBeInTheDocument()
    expect(screen.queryByText('æªè¨­å®')).not.toBeInTheDocument()
  })

  it('å¹³æãç¡ã passwordSet ãå½ãªããæªè¨­å®ããåºã', () => {
    render(<SessionShareModal {...baseProps} passwordSet={false} />)
    expect(screen.getByText('æªè¨­å®')).toBeInTheDocument()
  })

  it('åçææåå¾ã«æ°ãã¹ã¯ã¼ãã¨åè¡¨ç¤ºä¸å¯ã®è­¦åãè¡¨ç¤ºãã', async () => {
    vi.mocked(apiPost).mockResolvedValueOnce({
      success: true,
      data: { session_password: 'NewPass42' },
    })
    render(<SessionShareModal {...baseProps} passwordSet={true} />)
    fireEvent.click(screen.getByRole('button', { name: /åçæ/ }))
    await waitFor(() => expect(screen.getByText('NewPass42')).toBeInTheDocument())
    // åè¡¨ç¤ºä¸å¯ã®è­¦å (role=alert) ãåºã
    const alerts = screen.getAllByRole('alert')
    expect(alerts.some((el) => /åè¡¨ç¤ºã§ãã¾ãã/.test(el.textContent || ''))).toBe(true)
  })
})
