/**
 * useHapticFeedback テスト (Phase C speed slice)
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'

import { useHapticFeedback } from '../useHapticFeedback'

describe('useHapticFeedback', () => {
  let vibrateMock: ReturnType<typeof vi.fn>
  let originalVibrate: Navigator['vibrate'] | undefined
  type VibrateNav = Navigator & { vibrate?: (pattern: number | number[]) => boolean }

  beforeEach(() => {
    vibrateMock = vi.fn(() => true)
    originalVibrate = (navigator as VibrateNav).vibrate
    ;(navigator as VibrateNav).vibrate = vibrateMock as unknown as Navigator['vibrate']
  })
  afterEach(() => {
    ;(navigator as VibrateNav).vibrate = originalVibrate
  })

  it('tap calls navigator.vibrate(20)', () => {
    const { result } = renderHook(() => useHapticFeedback())
    act(() => result.current.tap())
    expect(vibrateMock).toHaveBeenCalledWith(20)
  })

  it('strokeConfirm calls a 2-stage pattern', () => {
    const { result } = renderHook(() => useHapticFeedback())
    act(() => result.current.strokeConfirm())
    expect(vibrateMock).toHaveBeenCalledWith([10, 30, 10])
  })

  it('undo / modeSwitch / error each fire distinct vibrate patterns', () => {
    const { result } = renderHook(() => useHapticFeedback())
    act(() => result.current.undo())
    expect(vibrateMock).toHaveBeenLastCalledWith(60)
    act(() => result.current.modeSwitch())
    expect(vibrateMock).toHaveBeenLastCalledWith([15, 50, 15])
    act(() => result.current.error())
    expect(vibrateMock).toHaveBeenLastCalledWith(200)
  })

  it('graceful no-op when navigator.vibrate is missing', () => {
    delete (navigator as VibrateNav).vibrate
    const { result } = renderHook(() => useHapticFeedback())
    expect(() => act(() => result.current.tap())).not.toThrow()
  })

  it('graceful no-op when navigator.vibrate throws', () => {
    ;(navigator as VibrateNav).vibrate = () => { throw new Error('not allowed') }
    const { result } = renderHook(() => useHapticFeedback())
    expect(() => act(() => result.current.strokeConfirm())).not.toThrow()
  })
})
