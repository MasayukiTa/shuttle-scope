/**
 * グローバル error / unhandledrejection ハンドラ:
 * 本番では stack・ファイル位置・生の reason を画面に出さず、エラー ID だけを出す。
 */
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { installGlobalErrorHandlers, GLOBAL_ERROR_BAR_ID } from '../globalErrorHandler'

const SECRET = 'internalFunctionName exploded at https://internal.example/api/secret'

function fireError(message: string) {
  window.dispatchEvent(
    new ErrorEvent('error', {
      error: new Error(message),
      message,
      filename: '/assets/index-ABC123.js',
      lineno: 12,
      colno: 34,
    }),
  )
}

function fireRejection(reason: unknown) {
  const ev = new Event('unhandledrejection')
  Object.assign(ev, { reason })
  window.dispatchEvent(ev)
}

function barText(): string {
  return document.getElementById(GLOBAL_ERROR_BAR_ID)?.textContent ?? ''
}

describe('installGlobalErrorHandlers', () => {
  let uninstall: (() => void) | null = null

  beforeEach(() => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    uninstall?.()
    uninstall = null
    document.getElementById(GLOBAL_ERROR_BAR_ID)?.remove()
    vi.restoreAllMocks()
    vi.useRealTimers()
  })

  it('production: hides message, stack and file position, shows an error id', () => {
    uninstall = installGlobalErrorHandlers({ showDetails: false })
    fireError(SECRET)
    const text = barText()
    expect(text).not.toContain('internalFunctionName')
    expect(text).not.toContain('internal.example')
    expect(text).not.toContain('index-ABC123.js')
    expect(text).not.toContain('Error:')
    expect(text).toMatch(/E-[0-9A-Z]+-[0-9A-Z]+/)
  })

  it('production: keeps the details in the console only', () => {
    uninstall = installGlobalErrorHandlers({ showDetails: false })
    fireError(SECRET)
    const logged = (console.error as unknown as ReturnType<typeof vi.fn>).mock.calls
      .map((c) => c.map(String).join(' '))
      .join('\n')
    expect(logged).toContain('internalFunctionName')
  })

  it('production: hides the raw rejection reason', () => {
    uninstall = installGlobalErrorHandlers({ showDetails: false })
    fireRejection(new Error(SECRET))
    const text = barText()
    expect(text).not.toContain('internalFunctionName')
    expect(text).toMatch(/E-[0-9A-Z]+-[0-9A-Z]+/)
  })

  it('production: replaces the bar instead of stacking and removes it after a while', () => {
    vi.useFakeTimers()
    uninstall = installGlobalErrorHandlers({ showDetails: false })
    fireError('first failure')
    vi.advanceTimersByTime(6_000)
    fireError('second failure')
    expect(document.querySelectorAll(`#${GLOBAL_ERROR_BAR_ID}`).length).toBe(1)
    expect((barText().match(/E-[0-9A-Z]+-[0-9A-Z]+/g) ?? []).length).toBe(1)
    vi.advanceTimersByTime(11_000)
    expect(document.getElementById(GLOBAL_ERROR_BAR_ID)).toBeNull()
  })

  it('production: ignores a benign AbortError rejection', () => {
    uninstall = installGlobalErrorHandlers({ showDetails: false })
    fireRejection({ name: 'AbortError', message: 'The operation was aborted.' })
    expect(document.getElementById(GLOBAL_ERROR_BAR_ID)).toBeNull()
  })

  it('development: still shows the message and the file position', () => {
    uninstall = installGlobalErrorHandlers({ showDetails: true })
    fireError(SECRET)
    const text = barText()
    expect(text).toContain('internalFunctionName')
    expect(text).toContain('index-ABC123.js:12:34')
  })
})
