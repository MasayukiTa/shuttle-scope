import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render } from '@testing-library/react'

vi.mock('@/api/client', () => ({ apiPost: vi.fn().mockResolvedValue({}), apiGet: vi.fn() }))
vi.mock('@/utils/analytics', () => ({ trackTutorialStep: vi.fn() }))
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string, o?: { defaultValue?: string }) => o?.defaultValue ?? k }),
}))

import { TutorialOverlay } from '../TutorialOverlay'

// 対象要素を既知の矩形で画面に置くヘルパ。
function placeTarget(rect: { top: number; left: number; width: number; height: number }) {
  const el = document.createElement('div')
  el.setAttribute('data-tutorial', 'spot')
  el.getBoundingClientRect = () =>
    ({
      top: rect.top,
      left: rect.left,
      width: rect.width,
      height: rect.height,
      right: rect.left + rect.width,
      bottom: rect.top + rect.height,
      x: rect.left,
      y: rect.top,
      toJSON: () => {},
    }) as DOMRect
  document.body.appendChild(el)
  return el
}

const tutorial = {
  id: 't_spot',
  title: 'T',
  steps: [{ title: 'S', body: 'b', target: '[data-tutorial="spot"]' }],
}

describe('TutorialOverlay: 対象を切り抜いて明るく見せ、吹き出しは隣に置く (要望3)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    // jsdom は innerWidth/innerHeight が 0 のことがあるので固定する。
    Object.defineProperty(window, 'innerWidth', { value: 1200, configurable: true })
    Object.defineProperty(window, 'innerHeight', { value: 800, configurable: true })
  })
  afterEach(() => {
    vi.useRealTimers()
    document.body.innerHTML = ''
  })

  it('切り抜き穴 (tutorial-spotlight-hole) が対象の位置・大きさで描かれる', async () => {
    placeTarget({ top: 300, left: 500, width: 120, height: 40 })
    const { container } = render(
      <TutorialOverlay tutorial={tutorial as never} onClose={() => {}} />,
    )
    await act(async () => { vi.advanceTimersByTime(400) })
    const hole = container.querySelector('.tutorial-spotlight-hole') as HTMLElement | null
    expect(hole).toBeTruthy()
    // PAD=6 を四方に足した矩形。クランプの範囲内なので素直に広がる。
    expect(hole!.style.top).toBe('294px')
    expect(hole!.style.left).toBe('494px')
    expect(hole!.style.width).toBe('132px')
    expect(hole!.style.height).toBe('52px')
  })

  it('暗幕の切り抜き穴はクリックを拾わない (対象を操作できる)', async () => {
    placeTarget({ top: 300, left: 500, width: 120, height: 40 })
    const { container } = render(
      <TutorialOverlay tutorial={tutorial as never} onClose={() => {}} />,
    )
    await act(async () => { vi.advanceTimersByTime(400) })
    const hole = container.querySelector('.tutorial-spotlight-hole') as HTMLElement
    // インライン style で pointer-events を上書きしていない (CSS 側で none)。
    // 要素自体に pointer-events:auto が付いていないことを確認する。
    expect(hole.style.pointerEvents).toBe('')
  })

  it('吹き出しは対象の矩形と重ならない (隣に置かれる)', async () => {
    const tgt = { top: 300, left: 500, width: 120, height: 40 }
    placeTarget(tgt)
    const { container } = render(
      <TutorialOverlay tutorial={tutorial as never} onClose={() => {}} />,
    )
    await act(async () => { vi.advanceTimersByTime(400) })
    const tip = container.querySelector('.tutorial-tooltip-attention') as HTMLElement
    expect(tip).toBeTruthy()
    const top = parseFloat(tip.style.top)
    const left = parseFloat(tip.style.left)
    // 下に十分な空き (800 - 340 = 460 >= 200+14) があるので対象の下に出る。
    // 吹き出しの上端 (top) は対象の下端 (340) 以降にある = 重ならない。
    expect(top).toBeGreaterThanOrEqual(340)
    // 横方向は対象の中央寄せだが、ここでは縦の非重なりで十分。
    expect(Number.isFinite(left)).toBe(true)
  })

  it('下に空きが無い対象では吹き出しを上に出す (やはり重ならない)', async () => {
    // 画面下端に貼り付いた対象 → 下に置けないので上へ。
    const tgt = { top: 740, left: 500, width: 120, height: 40 }
    placeTarget(tgt)
    const { container } = render(
      <TutorialOverlay tutorial={tutorial as never} onClose={() => {}} />,
    )
    await act(async () => { vi.advanceTimersByTime(400) })
    const tip = container.querySelector('.tutorial-tooltip-attention') as HTMLElement
    const top = parseFloat(tip.style.top)
    // 対象の上端 (740 - PAD=734) より上 (= top + 吹き出し高 <= 734) に出る。
    expect(top).toBeLessThan(734)
  })
})
