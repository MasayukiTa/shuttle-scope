// CollapsibleSection: 閉じている間は子を描画せず (= API 取得も走らず)、開くと現れる
import { describe, it, expect } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { CollapsibleSection } from '../CollapsibleSection'

function Child({ onMount }: { onMount: () => void }) {
  onMount()
  return <div data-testid="child">child</div>
}

describe('CollapsibleSection', () => {
  it('既定は閉じていて、子を描画しない', () => {
    let mounted = 0
    render(
      <CollapsibleSection title="見出し" description="補足">
        <Child onMount={() => { mounted++ }} />
      </CollapsibleSection>,
    )
    expect(screen.getByRole('button', { name: /見出し/ }).getAttribute('aria-expanded')).toBe('false')
    expect(screen.queryByTestId('child')).toBeNull()
    expect(mounted).toBe(0)
    expect(screen.getByText('補足')).toBeTruthy()
  })

  it('クリックで開き、もう一度で閉じる', () => {
    render(
      <CollapsibleSection title="見出し">
        <div data-testid="child">child</div>
      </CollapsibleSection>,
    )
    const btn = screen.getByRole('button', { name: /見出し/ })
    fireEvent.click(btn)
    expect(btn.getAttribute('aria-expanded')).toBe('true')
    expect(screen.getByTestId('child')).toBeTruthy()
    fireEvent.click(btn)
    expect(btn.getAttribute('aria-expanded')).toBe('false')
    expect(screen.queryByTestId('child')).toBeNull()
  })

  it('defaultOpen なら最初から開いている', () => {
    render(
      <CollapsibleSection title="見出し" defaultOpen>
        <div data-testid="child">child</div>
      </CollapsibleSection>,
    )
    expect(screen.getByTestId('child')).toBeTruthy()
  })
})
