/**
 * TopBarMenu / TopBarMenuSection 基本動作テスト。
 */
import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import { TopBarMenu, TopBarMenuSection } from '../TopBarMenu'

describe('TopBarMenu', () => {
  it('初期状態は閉じている (children は描画されない)', () => {
    render(
      <TopBarMenu>
        <button>hidden item</button>
      </TopBarMenu>,
    )
    expect(screen.queryByText('hidden item')).toBeNull()
  })

  it('⋮ クリックで開閉する', () => {
    render(
      <TopBarMenu>
        <button>visible item</button>
      </TopBarMenu>,
    )
    const trigger = screen.getByRole('button')
    expect(trigger.getAttribute('aria-expanded')).toBe('false')
    fireEvent.click(trigger)
    expect(trigger.getAttribute('aria-expanded')).toBe('true')
    expect(screen.getByText('visible item')).toBeTruthy()
  })

  it('Esc で閉じる', () => {
    render(
      <TopBarMenu>
        <button>item</button>
      </TopBarMenu>,
    )
    fireEvent.click(screen.getByRole('button', { name: /メニュー/ }))
    expect(screen.getByText('item')).toBeTruthy()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByText('item')).toBeNull()
  })
})

describe('TopBarMenuSection', () => {
  it('title が見出しとして表示される', () => {
    render(
      <TopBarMenuSection title="記録モード" firstSection>
        <button>item</button>
      </TopBarMenuSection>,
    )
    expect(screen.getByText('記録モード')).toBeTruthy()
    expect(screen.getByText('item')).toBeTruthy()
  })

  it('firstSection=true なら上区切り線が出ない', () => {
    const { container } = render(
      <TopBarMenuSection title="A" firstSection>
        <span>x</span>
      </TopBarMenuSection>,
    )
    expect(container.querySelectorAll('.border-t').length).toBe(0)
  })

  it('firstSection=false (デフォルト) なら上区切り線が出る', () => {
    const { container } = render(
      <TopBarMenuSection title="B">
        <span>x</span>
      </TopBarMenuSection>,
    )
    expect(container.querySelectorAll('.border-t').length).toBe(1)
  })
})
