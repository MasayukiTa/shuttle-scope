/**
 * useBreakpoint テスト
 *
 * jsdom はリサイズイベントをサポートしないため window.innerWidth の直接代入 +
 * resize イベント発火で検証する。
 */
import { describe, it, expect } from 'vitest'
import { act, renderHook } from '@testing-library/react'

import { useBreakpoint, BREAKPOINTS } from '../useBreakpoint'

function setWindowWidth(width: number) {
  Object.defineProperty(window, 'innerWidth', {
    configurable: true,
    writable: true,
    value: width,
  })
  window.dispatchEvent(new Event('resize'))
}

describe('useBreakpoint', () => {
  it('xs を返す: 480px 未満', () => {
    setWindowWidth(360)
    const { result } = renderHook(() => useBreakpoint())
    expect(result.current.bp).toBe('xs')
    expect(result.current.atLeast('xs')).toBe(true)
    expect(result.current.atLeast('sm')).toBe(false)
    expect(result.current.below('md')).toBe(true)
  })

  it('sm を返す: 640px 以上 768px 未満', () => {
    setWindowWidth(700)
    const { result } = renderHook(() => useBreakpoint())
    expect(result.current.bp).toBe('sm')
    expect(result.current.atLeast('sm')).toBe(true)
    expect(result.current.atLeast('md')).toBe(false)
  })

  it('md を返す: 768px 以上 1024px 未満', () => {
    setWindowWidth(900)
    const { result } = renderHook(() => useBreakpoint())
    expect(result.current.bp).toBe('md')
    expect(result.current.atLeast('md')).toBe(true)
    expect(result.current.atLeast('lg')).toBe(false)
  })

  it('lg を返す: 1024px 以上 1200px 未満', () => {
    setWindowWidth(1100)
    const { result } = renderHook(() => useBreakpoint())
    expect(result.current.bp).toBe('lg')
    expect(result.current.atLeast('lg')).toBe(true)
    expect(result.current.below('xl')).toBe(true)
  })

  it('xl を返す: 1200px 以上 1440px 未満 (Tailwind カスタム値)', () => {
    setWindowWidth(1300)
    const { result } = renderHook(() => useBreakpoint())
    expect(result.current.bp).toBe('xl')
  })

  it('2xl を返す: 1440px 以上 (Tailwind カスタム値)', () => {
    setWindowWidth(1600)
    const { result } = renderHook(() => useBreakpoint())
    expect(result.current.bp).toBe('2xl')
    expect(result.current.atLeast('2xl')).toBe(true)
  })

  it('リサイズで bp が更新される', () => {
    setWindowWidth(360)
    const { result } = renderHook(() => useBreakpoint())
    expect(result.current.bp).toBe('xs')

    act(() => {
      setWindowWidth(1300)
    })
    expect(result.current.bp).toBe('xl')
  })

  it('BREAKPOINTS は tailwind.config.js と一致する値を持つ', () => {
    // tailwind.config.js の screens と乖離していないことを構造的に確認
    expect(BREAKPOINTS.xs).toBe(480)
    expect(BREAKPOINTS.sm).toBe(640)
    expect(BREAKPOINTS.md).toBe(768)
    expect(BREAKPOINTS.lg).toBe(1024)
    expect(BREAKPOINTS.xl).toBe(1200)
    expect(BREAKPOINTS['2xl']).toBe(1440)
  })
})
