/**
 * Camera / Viewer 参加 CTA: セッションコードだけでは有効化せず、
 * パスワードが入力されるまで disabled のままにする (項目510)。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import ja from '@/i18n/ja.json'

vi.mock('@/api/client', () => ({ apiPost: vi.fn(), getParticipantIceConfig: vi.fn() }))
vi.mock('@/hooks/useDeviceHeartbeat', () => ({ useDeviceHeartbeat: () => {} }))

import { ViewerPage } from '../ViewerPage'
import { CameraSenderPage } from '../CameraSenderPage'

const viewerJoin = (ja as unknown as { auto: { ViewerPage: Record<string, string> } }).auto.ViewerPage.k9
const cameraJoin = (ja as unknown as { camera_sender: Record<string, string> }).camera_sender.join_button

describe('participant join CTA password gating (項目510)', () => {
  beforeEach(() => { localStorage.clear() })

  it('Viewer: code alone keeps join disabled; code + password enables it', () => {
    const { container } = render(<MemoryRouter><ViewerPage /></MemoryRouter>)
    const btn = screen.getByRole('button', { name: viewerJoin })
    const code = container.querySelector('input[type="text"]') as HTMLInputElement
    fireEvent.change(code, { target: { value: 'ABC123' } })
    expect(btn).toBeDisabled()
    const pwd = container.querySelector('input[type="password"]') as HTMLInputElement
    fireEvent.change(pwd, { target: { value: 'secret' } })
    expect(btn).toBeEnabled()
  })

  it('Camera: code alone keeps join disabled; code + password enables it', () => {
    const { container } = render(<MemoryRouter><CameraSenderPage /></MemoryRouter>)
    const btn = screen.getByRole('button', { name: cameraJoin })
    const code = container.querySelector('input[type="text"]') as HTMLInputElement
    fireEvent.change(code, { target: { value: 'ABC123' } })
    expect(btn).toBeDisabled()
    const pwd = container.querySelector('input[type="password"]') as HTMLInputElement
    fireEvent.change(pwd, { target: { value: 'secret' } })
    expect(btn).toBeEnabled()
  })
})
