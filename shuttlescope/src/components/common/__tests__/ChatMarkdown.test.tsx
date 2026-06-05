// @vitest-environment jsdom
import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import { ChatMarkdown } from '../ChatMarkdown'

describe('ChatMarkdown', () => {
  it('renders bold, inline code, and code fences', () => {
    const { container } = render(
      <ChatMarkdown content={'**bold** and `code`\n```js\nconst x = 1\n```'} />,
    )
    expect(container.querySelector('strong')?.textContent).toBe('bold')
    expect(container.querySelector('code')).toBeTruthy()
    expect(container.querySelector('pre')).toBeTruthy()
  })

  it('renders a GitHub pipe table as a <table>', () => {
    const md = '| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |'
    const { container } = render(<ChatMarkdown content={md} />)
    expect(container.querySelector('table')).toBeTruthy()
    expect(container.querySelectorAll('th').length).toBe(2)
    expect(container.querySelectorAll('tbody tr').length).toBe(2)
  })

  it('preserves the ordered-list start number', () => {
    const { container } = render(<ChatMarkdown content={'3. three\n4. four'} />)
    expect(container.querySelector('ol')?.getAttribute('start')).toBe('3')
  })

  it('is XSS-safe: HTML/script/javascript: in content becomes inert text, not live DOM', () => {
    const evil =
      '<script>alert(1)</script> <img src=x onerror=alert(2)> [click](javascript:alert(3)) **<b>x</b>**'
    const { container } = render(<ChatMarkdown content={evil} />)
    // Nothing from the model output is promoted to a live element.
    expect(container.querySelector('script')).toBeNull()
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('a[href^="javascript:"]')).toBeNull()
    // The raw markup survives only as escaped text.
    expect(container.textContent).toContain('<script>alert(1)</script>')
  })

  it('never throws on malformed / partial / streaming input', () => {
    const cases = ['', '```unclosed', '| a | b', '**', '> ', '###', '1. a\n3. b', '`x', '|||', '* * *', '~~~', '****']
    for (const s of cases) {
      expect(() => render(<ChatMarkdown content={s} />)).not.toThrow()
    }
  })
})
