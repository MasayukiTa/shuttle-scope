/**
 * PlayerSelectorSheet 基本動作テスト。
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import { PlayerSelectorSheet, type PlayerOption } from '../PlayerSelectorSheet'

const players: PlayerOption[] = [
  { id: 1, name: '田中太郎', team: 'A大学' },
  { id: 2, name: '佐藤花子', team: 'B高校' },
  { id: 3, name: '鈴木一郎', team: null },
]

describe('PlayerSelectorSheet', () => {
  it('open=false のときレンダリングしない', () => {
    const { container } = render(
      <PlayerSelectorSheet
        open={false}
        onClose={() => {}}
        players={players}
        onSelect={() => {}}
      />,
    )
    expect(container.firstChild).toBeNull()
  })

  it('全選手が表示される', () => {
    render(
      <PlayerSelectorSheet
        open
        onClose={() => {}}
        players={players}
        onSelect={() => {}}
      />,
    )
    expect(screen.getByText('田中太郎')).toBeTruthy()
    expect(screen.getByText('佐藤花子')).toBeTruthy()
    expect(screen.getByText('鈴木一郎')).toBeTruthy()
  })

  it('検索でフィルタされる (名前一致)', () => {
    render(
      <PlayerSelectorSheet
        open
        onClose={() => {}}
        players={players}
        onSelect={() => {}}
      />,
    )
    const input = screen.getByRole('searchbox')
    fireEvent.change(input, { target: { value: '佐藤' } })
    expect(screen.getByText('佐藤花子')).toBeTruthy()
    expect(screen.queryByText('田中太郎')).toBeNull()
  })

  it('検索でフィルタされる (チーム名一致)', () => {
    render(
      <PlayerSelectorSheet
        open
        onClose={() => {}}
        players={players}
        onSelect={() => {}}
      />,
    )
    const input = screen.getByRole('searchbox')
    fireEvent.change(input, { target: { value: 'B高校' } })
    expect(screen.getByText('佐藤花子')).toBeTruthy()
    expect(screen.queryByText('田中太郎')).toBeNull()
  })

  it('選手クリックで onSelect + onClose が呼ばれる', () => {
    const onSelect = vi.fn()
    const onClose = vi.fn()
    render(
      <PlayerSelectorSheet
        open
        onClose={onClose}
        players={players}
        onSelect={onSelect}
      />,
    )
    fireEvent.click(screen.getByText('田中太郎'))
    expect(onSelect).toHaveBeenCalledWith(players[0])
    expect(onClose).toHaveBeenCalled()
  })

  it('selectedId は aria-pressed=true でマーク', () => {
    render(
      <PlayerSelectorSheet
        open
        onClose={() => {}}
        players={players}
        selectedId={2}
        onSelect={() => {}}
      />,
    )
    const buttons = screen.getAllByRole('button', { pressed: true })
    expect(buttons).toHaveLength(1)
    expect(buttons[0].textContent).toContain('佐藤花子')
  })

  it('該当 0 件のとき empty メッセージを出す', () => {
    render(
      <PlayerSelectorSheet
        open
        onClose={() => {}}
        players={players}
        onSelect={() => {}}
      />,
    )
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'nomatch' } })
    expect(screen.getByText('該当する選手がいません')).toBeTruthy()
  })
})
