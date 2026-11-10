/**
 * operator-pending: 記録画面ヘッダーの「承認待ち N 台」バッジ。
 *
 * 承認待ちが 1 台以上あるとき、ヘッダー（共有ボタンの近く）にバッジを出し、
 * 押すと接続デバイス管理が開く。count=0 のときは何も出さない。
 * 実コンポーネントを描画して確かめる。
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { PendingDeviceBadge } from '../PendingDeviceBadge'

describe('PendingDeviceBadge — 承認待ちバッジ', () => {
  it('承認待ちが 1 台以上あるとバッジを出し、件数と日本語文言を表示する', () => {
    render(<PendingDeviceBadge count={1} onClick={() => {}} />)
    const badge = screen.getByTestId('pending-device-badge')
    expect(badge).toBeInTheDocument()
    // 「承認待ち 1 台」の日本語文言（実 i18n）
    expect(badge).toHaveTextContent('承認待ち')
    expect(badge).toHaveTextContent('1')
    // 件数バッジ
    expect(screen.getByTestId('pending-device-badge-count')).toHaveTextContent('1')
  })

  it('押すと接続デバイス管理を開くコールバックが呼ばれる', () => {
    const onClick = vi.fn()
    render(<PendingDeviceBadge count={2} onClick={onClick} />)
    fireEvent.click(screen.getByTestId('pending-device-badge'))
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('承認待ちが 0 台のときは何も描画しない', () => {
    const { container } = render(<PendingDeviceBadge count={0} onClick={() => {}} />)
    expect(container.firstChild).toBeNull()
    expect(screen.queryByTestId('pending-device-badge')).toBeNull()
  })
})
