/**
 * useKeyboard のフォーカスと記録ロックの回帰テスト。
 *
 * - ボタンやメニュー項目にフォーカスがあるとき、Enter でラリーを始めない
 *   (「操作メニュー」を Enter で開こうとして未保存ラリーが始まった不具合)。
 * - Tab は標準のフォーカス移動を優先する。Shift+Tab は常に標準のまま。
 * - inputLocked の間は動画操作以外を受け付けない。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { cleanup, renderHook } from '@testing-library/react'

import { useKeyboard } from '../useKeyboard'
import { useAnnotationStore } from '@/store/annotationStore'

// グローバルの keydown 監視を次のテストへ持ち越さない
afterEach(() => {
  cleanup()
})

function press(target: Element | Document, key: string, init: KeyboardEventInit = {}) {
  const ev = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init })
  target.dispatchEvent(ev)
  return ev
}

describe('useKeyboard: フォーカス中の部品を優先する', () => {
  let button: HTMLButtonElement

  beforeEach(() => {
    useAnnotationStore.getState().init(1, 1, 1, 1, 0, 0, 'player_a')
    button = document.createElement('button')
    document.body.appendChild(button)
  })

  afterEach(() => {
    button.remove()
  })

  it('何にもフォーカスがないときの Enter はラリーを開始する', () => {
    renderHook(() => useKeyboard())
    press(document.body, 'Enter')
    expect(useAnnotationStore.getState().isRallyActive).toBe(true)
  })

  it('ボタンにフォーカスがあるときの Enter はラリーを開始せず、既定動作も止めない', () => {
    renderHook(() => useKeyboard())
    const ev = press(button, 'Enter')
    expect(useAnnotationStore.getState().isRallyActive).toBe(false)
    expect(ev.defaultPrevented).toBe(false)
  })

  it('role=menuitem の中の Enter もラリーを開始しない', () => {
    const item = document.createElement('div')
    item.setAttribute('role', 'menuitem')
    const inner = document.createElement('span')
    item.appendChild(inner)
    document.body.appendChild(item)
    renderHook(() => useKeyboard())
    press(inner, 'Enter')
    expect(useAnnotationStore.getState().isRallyActive).toBe(false)
    item.remove()
  })

  it('ボタンにフォーカスがあるときの Tab は打者切替に使わない', () => {
    useAnnotationStore.setState({ isRallyActive: true })
    const onToggleHitter = vi.fn()
    renderHook(() => useKeyboard({ onToggleHitter }))
    const ev = press(button, 'Tab')
    expect(onToggleHitter).not.toHaveBeenCalled()
    expect(ev.defaultPrevented).toBe(false)
  })

  it('Shift+Tab は打者切替に使わない', () => {
    useAnnotationStore.setState({ isRallyActive: true })
    const onToggleHitter = vi.fn()
    renderHook(() => useKeyboard({ onToggleHitter }))
    const ev = press(document.body, 'Tab', { shiftKey: true })
    expect(onToggleHitter).not.toHaveBeenCalled()
    expect(ev.defaultPrevented).toBe(false)
  })

  it('ラリー中、フォーカスがない状態の Tab は従来どおり打者切替', () => {
    useAnnotationStore.setState({ isRallyActive: true })
    const onToggleHitter = vi.fn()
    renderHook(() => useKeyboard({ onToggleHitter }))
    press(document.body, 'Tab')
    expect(onToggleHitter).toHaveBeenCalledTimes(1)
  })
})

describe('useKeyboard: inputLocked', () => {
  beforeEach(() => {
    useAnnotationStore.getState().init(1, 1, 1, 1, 0, 0, 'player_a')
  })

  it('ロック中は Enter でラリーを始めない', () => {
    renderHook(() => useKeyboard({ inputLocked: true }))
    press(document.body, 'Enter')
    expect(useAnnotationStore.getState().isRallyActive).toBe(false)
  })

  it('ロック中でも動画のシークは動く', () => {
    const video = document.createElement('video')
    const videoRef = { current: video } as React.RefObject<HTMLVideoElement>
    // jsdom のメディア要素は再生状態を持たないので、値だけの単純な属性に置き換える
    Object.defineProperty(video, 'duration', { value: 100, configurable: true })
    Object.defineProperty(video, 'currentTime', { value: 20, writable: true, configurable: true })
    renderHook(() => useKeyboard({ videoRef, inputLocked: true }))
    press(document.body, 'ArrowRight', { shiftKey: true })
    expect(video.currentTime).toBe(30)
  })

  it('ロックを外せば Enter でラリーを始められる', () => {
    renderHook(() => useKeyboard({ inputLocked: false }))
    press(document.body, 'Enter')
    expect(useAnnotationStore.getState().isRallyActive).toBe(true)
  })
})
