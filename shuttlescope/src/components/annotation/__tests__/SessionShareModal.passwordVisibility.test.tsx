import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

import { SessionShareModal } from '../SessionShareModal'

vi.mock('@/api/client', () => ({
  apiPost: vi.fn(),
}))
// jsdom には canvas が無いので QR 生成は失敗するが、ここではパスワード表示だけを見る
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

describe('SessionShareModal password visibility', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows "設定済み" (not "未設定") when password_set is true but the plaintext is not available (after reload)', () => {
    // 再読み込み後: 平文は無いが password_set=true。サーバーはハッシュを保持している。
    render(<SessionShareModal {...baseProps} passwordSet={true} />)
    expect(
      screen.getByText('設定済み（再表示はできません。必要なら再生成してください）'),
    ).toBeInTheDocument()
    expect(screen.queryByText('未設定')).not.toBeInTheDocument()
  })

  it('shows "未設定" only when the server has no password (password_set false, no plaintext)', () => {
    render(<SessionShareModal {...baseProps} passwordSet={false} />)
    expect(screen.getByText('未設定')).toBeInTheDocument()
    expect(
      screen.queryByText('設定済み（再表示はできません。必要なら再生成してください）'),
    ).not.toBeInTheDocument()
  })

  it('reveals the freshly issued password in large monospace text with a one-time warning', () => {
    // 発行直後: 平文が props で渡る。閉じる前の警告つきで大きく等幅表示する。
    render(<SessionShareModal {...baseProps} sessionPassword="Kp7Rtw9q" />)
    // 一度きりの警告
    expect(
      screen.getByText(
        'このパスワードは今だけ表示されます。閉じると再表示できません。必ず控えてください。',
      ),
    ).toBeInTheDocument()
    // 大きい等幅のパスワード本体が見える（警告ブロック内の font-mono / text-xl）
    const reveal = screen.getByText('Kp7Rtw9q', {
      selector: 'p.font-mono',
    })
    expect(reveal).toBeInTheDocument()
    expect(reveal.className).toContain('text-xl')
    expect(reveal.className).toContain('font-mono')
    // 発行直後は「未設定」を出さない
    expect(screen.queryByText('未設定')).not.toBeInTheDocument()
  })
})
