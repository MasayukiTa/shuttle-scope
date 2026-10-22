import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import { SessionShareModal } from '../SessionShareModal'

vi.mock('@/api/client', () => ({
  apiPost: vi.fn(),
}))
// jsdom には canvas が無いので QR 生成は失敗する。失敗を表示する経路の検査に使う
vi.mock('qrcode', () => ({
  default: { toCanvas: vi.fn(() => Promise.reject(new Error('no canvas'))) },
}))

const props = {
  sessionCode: 'ABC123',
  coachUrls: ['http://192.168.0.5:5173/#/annotator/1'],
  cameraSenderUrls: ['http://192.168.0.5:5173/#/camera/ABC123'],
  viewerUrls: ['http://192.168.0.5:5173/#/viewer/ABC123'],
  sessionPassword: 'pw-1234',
  onClose: vi.fn(),
}

describe('SessionShareModal accessibility and failure display', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('names the dialog by its visible title and names the close button', () => {
    render(<SessionShareModal {...props} />)
    const dialog = screen.getByRole('dialog')
    const labelledBy = dialog.getAttribute('aria-labelledby')
    expect(labelledBy).toBeTruthy()
    expect(document.getElementById(labelledBy as string)?.textContent).toBe('セッション共有')
    expect(screen.getByRole('button', { name: '閉じる' })).toBeInTheDocument()
  })

  it('shows a message when the QR code cannot be drawn', async () => {
    render(<SessionShareModal {...props} />)
    const alerts = await screen.findAllByText(/QRコードを表示できませんでした/)
    expect(alerts.length).toBeGreaterThan(0)
  })

  it('does not report a copy as done when execCommand returns false', async () => {
    Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true })
    document.execCommand = vi.fn(() => false)
    render(<SessionShareModal {...props} />)
    fireEvent.click(screen.getAllByRole('button', { name: 'コピー' })[0])
    expect(await screen.findByText(/コピーできませんでした/)).toBeInTheDocument()
    expect(screen.queryByText('コピー済')).not.toBeInTheDocument()
  })
})
