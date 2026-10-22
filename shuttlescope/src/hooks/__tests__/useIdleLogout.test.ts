import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useIdleLogout } from '@/hooks/useIdleLogout'

const MIN = 60 * 1000
const TIMEOUT = 15 * MIN

describe('useIdleLogout', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('logs out after the idle timeout with no input', () => {
    const onIdle = vi.fn()
    renderHook(() => useIdleLogout({ enabled: true, timeoutMs: TIMEOUT, onIdle }))
    vi.advanceTimersByTime(TIMEOUT + 30_000)
    expect(onIdle).toHaveBeenCalled()
  })

  it('does not treat visibilitychange as activity', () => {
    const onIdle = vi.fn()
    renderHook(() => useIdleLogout({ enabled: true, timeoutMs: TIMEOUT, onIdle }))
    vi.advanceTimersByTime(14 * MIN)
    window.dispatchEvent(new Event('visibilitychange'))
    document.dispatchEvent(new Event('visibilitychange'))
    vi.advanceTimersByTime(2 * MIN)
    expect(onIdle).toHaveBeenCalled()
  })

  it('still treats real input as activity', () => {
    const onIdle = vi.fn()
    renderHook(() => useIdleLogout({ enabled: true, timeoutMs: TIMEOUT, onIdle }))
    vi.advanceTimersByTime(14 * MIN)
    window.dispatchEvent(new Event('keydown'))
    vi.advanceTimersByTime(2 * MIN)
    expect(onIdle).not.toHaveBeenCalled()
  })
})
