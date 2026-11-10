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

// QR にエンコードされたテキスト (toCanvas の第2引数) を集める。
function encodedTexts(): string[] {
  return toCanvas.mock.calls.map((c) => String(c[1]))
}

const LAN_COACH = 'http://192.168.0.5:5173/#/annotator/1'
const LAN_CAMERA = 'http://192.168.0.5:5173/#/camera/ABC123'
const LAN_VIEWER = 'http://192.168.0.5:5173/#/viewer/ABC123'
const LOCAL_COACH = 'http://localhost:5173/#/annotator/1'

const baseProps = {
  sessionCode: 'ABC123',
  coachUrls: [LAN_COACH, LOCAL_COACH],
  cameraSenderUrls: [LAN_CAMERA],
  viewerUrls: [LAN_VIEWER],
  onClose: vi.fn(),
}

describe('SessionShareModal public-origin QR rebasing', () => {
  beforeEach(() => {
    toCanvas.mockClear()
  })

  it('rebases the QR URLs onto the public https origin when the page is opened publicly', async () => {
    render(<SessionShareModal {...baseProps} publicOrigin="https://app.shuttle-scope.com" />)
    await waitFor(() => expect(toCanvas.mock.calls.length).toBeGreaterThanOrEqual(3))
    const encoded = encodedTexts()
    // 公開 origin が先頭になり、LAN IP ・ localhost は QR に使われない。
    expect(encoded).toContain('https://app.shuttle-scope.com/#/annotator/1')
    expect(encoded).toContain('https://app.shuttle-scope.com/#/camera/ABC123')
    expect(encoded).toContain('https://app.shuttle-scope.com/#/viewer/ABC123')
    for (const text of encoded) {
      expect(text).not.toContain('192.168.')
      expect(text).not.toContain('localhost')
    }
  })

  it('falls back to the LAN URLs in the QR when no public origin is given (localhost scenario)', async () => {
    render(<SessionShareModal {...baseProps} publicOrigin={null} />)
    await waitFor(() => expect(toCanvas.mock.calls.length).toBeGreaterThanOrEqual(3))
    const encoded = encodedTexts()
    // 従来通り LAN IP URL が QR に使われ、公開ドメインには差し替えない。
    expect(encoded).toContain(LAN_COACH)
    expect(encoded).toContain(LAN_CAMERA)
    expect(encoded).toContain(LAN_VIEWER)
    for (const text of encoded) {
      expect(text).not.toContain('app.shuttle-scope.com')
    }
  })
})
