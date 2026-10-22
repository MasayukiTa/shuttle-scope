/**
 * 設定モード: 現在値を支援技術へ返す (radiogroup / switch) と、打者切替の説明が平易であること
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

vi.mock('@/hooks/useBreakpoint', () => ({
  useBreakpoint: () => ({ atLeast: () => true }),
}))

import { SettingsModePanel } from '../SettingsModePanel'

function renderPanel(props: Partial<React.ComponentProps<typeof SettingsModePanel>> = {}) {
  return render(
    <SettingsModePanel
      isMatchDayMode={false}
      onToggleMatchDayMode={() => {}}
      isBasicMode={false}
      onToggleAnnotationMode={() => {}}
      {...props}
    />,
  )
}

describe('SettingsModePanel accessibility', () => {
  it('排他選択は radiogroup で、選択中の値が aria-checked になる', () => {
    const onSet = vi.fn()
    renderPanel({ playerAStart: 'bottom', onSetPlayerAStart: onSet })
    const groups = screen.getAllByRole('radiogroup')
    expect(groups.length).toBeGreaterThanOrEqual(2)
    for (const g of groups) {
      expect(g.getAttribute('aria-labelledby')).toBeTruthy()
      expect(g.querySelectorAll('[role="radio"][aria-checked="true"]')).toHaveLength(1)
    }
    const top = screen.getAllByRole('radio').find((r) => r.getAttribute('aria-checked') === 'false')
    expect(top).toBeTruthy()
    fireEvent.click(top as HTMLElement)
  })

  it('ON/OFF は switch で、状態が aria-checked になる', () => {
    renderPanel({ isMatchDayMode: true })
    const switches = screen.getAllByRole('switch')
    expect(switches.length).toBeGreaterThanOrEqual(2)
    expect(switches[0].getAttribute('aria-checked')).toBe('true')
    expect(switches[1].getAttribute('aria-checked')).toBe('true')
  })

  it('打者の切替方法の説明に実装語 (flip / tap / revert) を出さない', () => {
    const { container } = renderPanel()
    const text = container.textContent ?? ''
    expect(text).toContain('打者の切り替え方法')
    expect(text).not.toMatch(/flip|tap|revert|semi-auto/i)
  })
})
