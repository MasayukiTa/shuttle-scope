/**
 * 本番観察 (2026-11-10): 記録画面を幅 307px 等で開くと上バーが折り返しきれず、
 * 右端の ⋮ overflow メニューごと画面外に切れて、その中にしか無かった「共有」に
 * 到達できなかった。対策として共有を ⋮ から独立させ、狭幅ヘッダーに常時可視の
 * MobileShareButton を置いた。
 *
 * このテストは Tailwind クラス文字列の写経ではなく、実際に DOM へレンダリングして
 * 「どの状態でも共有ボタンが描画され、押せる (onOpenShare が発火する)」ことを固定する。
 * 狭い幅 (307px) のコンテナに入れても共有ボタンが可視で操作可能であることまで確かめる。
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import { MobileShareButton } from '../MobileShareButton'

describe('MobileShareButton (狭幅ヘッダーの共有動線)', () => {
  it('セッション未作成でも「共有」ボタンが描画される', () => {
    render(<MobileShareButton activeSessionCode={null} onOpenShare={() => {}} />)
    const btn = screen.getByRole('button', { name: '共有' })
    expect(btn).toBeInTheDocument()
    // ラベルテキストとしても「共有」が見えている (アイコンのみに潰れていない)
    expect(btn).toHaveTextContent('共有')
  })

  it('セッションがあるときはセッションコードを表示しつつ共有動線を保つ', () => {
    render(<MobileShareButton activeSessionCode={'ABC123'} onOpenShare={() => {}} />)
    const btn = screen.getByRole('button', { name: '共有' })
    expect(btn).toHaveTextContent('ABC123')
  })

  it('クリックで onOpenShare が発火する (動線が生きている)', () => {
    const onOpenShare = vi.fn()
    render(<MobileShareButton activeSessionCode={null} onOpenShare={onOpenShare} />)
    fireEvent.click(screen.getByRole('button', { name: '共有' }))
    expect(onOpenShare).toHaveBeenCalledTimes(1)
  })

  it('幅 307px の狭いコンテナに入れても共有ボタンが描画され、押せる', () => {
    const onOpenShare = vi.fn()
    const { container } = render(
      <div style={{ width: 307, display: 'flex', overflow: 'hidden' }}>
        <MobileShareButton activeSessionCode={null} onOpenShare={onOpenShare} />
      </div>,
    )
    // 狭幅コンテナを明示している (回帰で親が固定の広い幅に戻っても気付けるよう pin)
    const wrapper = container.firstElementChild as HTMLElement
    expect(wrapper.style.width).toBe('307px')

    const btn = screen.getByRole('button', { name: '共有' })
    expect(btn).toBeInTheDocument()
    fireEvent.click(btn)
    expect(onOpenShare).toHaveBeenCalledTimes(1)
  })
})
