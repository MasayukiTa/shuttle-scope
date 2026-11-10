/**
 * 共通 ErrorBoundary: 本番では例外の内容・スタックトレースを画面に出さない。
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ErrorBoundary } from '../ErrorBoundary'

const SECRET_MESSAGE = 'internalFunctionName exploded at src/pages/Secret.tsx'

function Boom(): never {
  throw new Error(SECRET_MESSAGE)
}

describe('ErrorBoundary', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('does not show the message or the stack when details are hidden (production)', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const { container } = render(
      <ErrorBoundary showDetails={false}>
        <Boom />
      </ErrorBoundary>,
    )
    const text = container.textContent ?? ''
    expect(text).not.toContain('internalFunctionName')
    expect(text).not.toContain('Secret.tsx')
    expect(text).not.toContain('Component stack')
    expect(container.querySelector('pre')).toBeNull()
    expect(text).toMatch(/E-[0-9A-Z]+-[0-9A-Z]+/)
  })

  it('shows the message when details are enabled (development)', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    render(
      <ErrorBoundary showDetails>
        <Boom />
      </ErrorBoundary>,
    )
    expect(screen.getByText(SECRET_MESSAGE)).toBeTruthy()
  })
})
