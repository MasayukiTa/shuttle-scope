/**
 * CommandPalette: imperative open API + キー操作テスト。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'

import { CommandPalette, openCommandPalette, type PaletteCommand } from '../CommandPalette'

const baseCommands: PaletteCommand[] = [
  { id: 'a', label: 'モード切替', keywords: ['mode'], run: vi.fn() },
  { id: 'b', label: 'ラリー終了', keywords: ['rally', 'end'], run: vi.fn() },
  { id: 'c', label: 'アンドゥ', hint: 'Ctrl+Z', run: vi.fn() },
]

describe('CommandPalette', () => {
  beforeEach(() => {
    baseCommands.forEach((c) => (c.run as any).mockClear?.())
  })

  it('初期状態は閉じている', () => {
    render(<CommandPalette commands={baseCommands} />)
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('Ctrl+K で開く', () => {
    render(<CommandPalette commands={baseCommands} />)
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true })
    expect(screen.getByRole('dialog')).toBeTruthy()
  })

  it('Cmd+K (Mac) でも開く', () => {
    render(<CommandPalette commands={baseCommands} />)
    fireEvent.keyDown(window, { key: 'k', metaKey: true })
    expect(screen.getByRole('dialog')).toBeTruthy()
  })

  it('openCommandPalette() で外部から開ける', () => {
    render(<CommandPalette commands={baseCommands} />)
    act(() => {
      openCommandPalette()
    })
    expect(screen.getByRole('dialog')).toBeTruthy()
  })

  it('開いた状態で Esc が閉じる', () => {
    render(<CommandPalette commands={baseCommands} />)
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true })
    expect(screen.getByRole('dialog')).toBeTruthy()
    const input = screen.getByRole('textbox')
    fireEvent.keyDown(input, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('検索でフィルタされる', () => {
    render(<CommandPalette commands={baseCommands} />)
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true })
    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: 'mode' } })
    expect(screen.getByText('モード切替')).toBeTruthy()
    expect(screen.queryByText('ラリー終了')).toBeNull()
  })

  it('Enter で選択中のコマンドが実行される', () => {
    render(<CommandPalette commands={baseCommands} />)
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true })
    const input = screen.getByRole('textbox')
    fireEvent.keyDown(input, { key: 'ArrowDown' })  // index 1 = ラリー終了
    fireEvent.keyDown(input, { key: 'Enter' })
    // setTimeout 0 後に呼ばれるので flush
    return new Promise<void>((resolve) => {
      setTimeout(() => {
        expect(baseCommands[1].run).toHaveBeenCalled()
        resolve()
      }, 10)
    })
  })

  it('disabled なコマンドはクリック/Enter で実行されない', () => {
    const disabledCmd: PaletteCommand = { id: 'd', label: '無効', run: vi.fn(), disabled: true }
    render(<CommandPalette commands={[disabledCmd]} />)
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true })
    const item = screen.getByRole('option')
    fireEvent.click(item)
    return new Promise<void>((resolve) => {
      setTimeout(() => {
        expect(disabledCmd.run).not.toHaveBeenCalled()
        resolve()
      }, 10)
    })
  })

  it('ヘッダーに ↑↓/Enter/Esc のキーヒントが出る', () => {
    render(<CommandPalette commands={baseCommands} />)
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true })
    expect(screen.getByText('↑↓')).toBeTruthy()
    expect(screen.getByText('Enter')).toBeTruthy()
    expect(screen.getByText('Esc')).toBeTruthy()
  })
})
