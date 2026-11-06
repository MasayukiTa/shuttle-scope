/**
 * BottomSheet: drag handle gesture (#780 fix).
 * handle is a real affordance: pointer drag up expands, drag down collapses/closes,
 * a tap still toggles. previously only onClick/Esc existed (fake affordance).
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import { BottomSheet } from '../BottomSheet'

function getHandle(): HTMLElement {
  // the handle button carries aria-expanded
  return screen.getAllByRole('button').find((b) => b.hasAttribute('aria-expanded')) as HTMLElement
}

describe('BottomSheet drag handle', () => {
  it('starts collapsed (aria-expanded=false) and hides children', () => {
    render(
      <BottomSheet label="x">
        <div data-testid="content">body</div>
      </BottomSheet>,
    )
    const handle = getHandle()
    expect(handle.getAttribute('aria-expanded')).toBe('false')
    expect(screen.queryByTestId('content')).toBeNull()
  })

  it('drag up past threshold expands the sheet', () => {
    render(
      <BottomSheet label="x">
        <div data-testid="content">body</div>
      </BottomSheet>,
    )
    const handle = getHandle()
    fireEvent.pointerDown(handle, { clientY: 300, pointerId: 1, button: 0 })
    fireEvent.pointerMove(handle, { clientY: 300 - 40, pointerId: 1 })
    fireEvent.pointerUp(handle, { clientY: 260, pointerId: 1 })
    expect(handle.getAttribute('aria-expanded')).toBe('true')
    expect(screen.getByTestId('content')).toBeTruthy()
  })

  it('small move + click is treated as a tap toggle (no drag)', () => {
    render(
      <BottomSheet label="x">
        <div data-testid="content">body</div>
      </BottomSheet>,
    )
    const handle = getHandle()
    fireEvent.pointerDown(handle, { clientY: 300, pointerId: 1, button: 0 })
    fireEvent.pointerMove(handle, { clientY: 296, pointerId: 1 }) // below threshold
    fireEvent.pointerUp(handle, { clientY: 296, pointerId: 1 })
    fireEvent.click(handle)
    expect(handle.getAttribute('aria-expanded')).toBe('true')
  })

  it('drag down collapses when expanded (no onClose -> collapse only)', () => {
    render(
      <BottomSheet label="x" defaultOpen>
        <div data-testid="content">body</div>
      </BottomSheet>,
    )
    const handle = getHandle()
    expect(handle.getAttribute('aria-expanded')).toBe('true')
    fireEvent.pointerDown(handle, { clientY: 100, pointerId: 1, button: 0 })
    fireEvent.pointerMove(handle, { clientY: 100 + 40, pointerId: 1 })
    fireEvent.pointerUp(handle, { clientY: 140, pointerId: 1 })
    expect(handle.getAttribute('aria-expanded')).toBe('false')
  })

  it('drag down calls onClose when provided', () => {
    const onClose = vi.fn()
    render(
      <BottomSheet label="x" defaultOpen onClose={onClose}>
        <div data-testid="content">body</div>
      </BottomSheet>,
    )
    const handle = getHandle()
    fireEvent.pointerDown(handle, { clientY: 100, pointerId: 1, button: 0 })
    fireEvent.pointerMove(handle, { clientY: 140, pointerId: 1 })
    fireEvent.pointerUp(handle, { clientY: 140, pointerId: 1 })
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
