import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, waitFor } from '@testing-library/react'

import { SessionShareModal } from '../SessionShareModal'

const toCanvas = vi.fn((..._args: unknown[]) => Promise.resolve())

vi.mock('@/api/client', () => ({
  apiPost: vi.fn(),
}))
vi.mock('qrcode', () => ({
  default: { toCanvas: (...args: unknown[]) => toCanvas(...args) },
}))

const PASSWORD = 'pw-fake-1234'

const props = {
  sessionCode: 'ABC123',
  coachUrls: ['http://192.168.0.5:5173/#/annotator/1'],
  cameraSenderUrls: ['http://192.168.0.5:5173/#/camera/ABC123'],
  viewerUrls: ['http://192.168.0.5:5173/#/viewer/ABC123'],
  sessionPassword: PASSWORD,
  onClose: vi.fn(),
}

describe('SessionShareModal does not put the session password in URLs', () => {
  beforeEach(() => {
    toCanvas.mockClear()
  })

  it('encodes plain join URLs in the QR codes', async () => {
    render(<SessionShareModal {...props} />)
    await waitFor(() => expect(toCanvas.mock.calls.length).toBeGreaterThanOrEqual(3))
    const encoded = toCanvas.mock.calls.map((c) => String(c[1]))
    for (const text of encoded) {
      expect(text).not.toContain(PASSWORD)
      expect(text).not.toContain('pwd=')
    }
    expect(encoded).toContain(props.cameraSenderUrls[0])
    expect(encoded).toContain(props.viewerUrls[0])
  })

  it('shows plain join URLs as text', () => {
    const { container } = render(<SessionShareModal {...props} />)
    const urlTexts = Array.from(container.querySelectorAll('p.font-mono')).map((p) => p.textContent ?? '')
    expect(urlTexts.length).toBeGreaterThanOrEqual(2)
    for (const text of urlTexts) {
      expect(text).not.toContain(PASSWORD)
      expect(text).not.toContain('pwd=')
    }
  })
})
