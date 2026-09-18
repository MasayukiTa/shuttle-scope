/**
 * useHapticFeedback テスト (Phase C speed slice)
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'

import { useHapticFeedback } from '../useHapticFeedback'

describe('useHapticFeedback', () => {
  let vibrateMock: ReturnType<typeof vi.fn>
  let originalVibrate: ((pattern: number | number[]) => boolean) | undefined
  // lib.dom の Navigator.vibrate は必須プロパティなので、Navigator & {vibrate?}
  // だと「必須かつ optional」になり undefined 代入も delete もできない。
  // vibrate を外してから optional として付け直す。
  // (実機では PC ブラウザに vibrate が無いので optional が正しい)
  type VibrateNav = Omit<Navigator, 'vibrate'> & { vibrate?: (pattern: number | number[]) => boolean }
  const nav = navigator as unknown as VibrateNav

  beforeEach(() => {
    vibrateMock = vi.fn(() => true)
    originalVibrate = nav.vibrate
    ;nav.vibrate = vibrateMock as unknown as VibrateNav['vibrate']
  })
  afterEach(() => {
    ;nav.vibrate = originalVibrate
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
    delete nav.vibrate
    const { result } = renderHook(() => useHapticFeedback())
    expect(() => act(() => result.current.tap())).not.toThrow()
  })

  it('graceful no-op when navigator.vibrate throws', () => {
    ;(navigator as VibrateNav).vibrate = () => { throw new Error('not allowed') }
    const { result } = renderHook(() => useHapticFeedback())
    expect(() => act(() => result.current.strokeConfirm())).not.toThrow()
  })
})
