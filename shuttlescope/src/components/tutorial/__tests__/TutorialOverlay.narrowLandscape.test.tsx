import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render } from '@testing-library/react'

vi.mock('@/api/client', () => ({ apiPost: vi.fn().mockResolvedValue({}), apiGet: vi.fn() }))
vi.mock('@/utils/analytics', () => ({ trackTutorialStep: vi.fn() }))
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string, o?: { defaultValue?: string }) => o?.defaultValue ?? k }),
}))

import { TutorialOverlay } from '../TutorialOverlay'

// 吹き出しの推定サイズ (TutorialOverlay.tsx の TIP_W / 吹き出し className w-80=320px と揃える)。
const TIP_W = 320
const TIP_H = 200

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

function setViewport(w: number, h: number) {
  Object.defineProperty(window, 'innerWidth', { value: w, configurable: true })
  Object.defineProperty(window, 'innerHeight', { value: h, configurable: true })
}

// 吹き出し (tip) と対象の切り抜き穴 (hole) の矩形が重ならないことを検証する。
async function renderAndGetRects(tgt: { top: number; left: number; width: number; height: number }) {
  placeTarget(tgt)
  const { container } = render(
    <TutorialOverlay tutorial={tutorial as never} onClose={() => {}} />,
  )
  await act(async () => { vi.advanceTimersByTime(400) })
  const tip = container.querySelector('.tutorial-tooltip-attention') as HTMLElement
  const hole = container.querySelector('.tutorial-spotlight-hole') as HTMLElement
  expect(tip).toBeTruthy()
  expect(hole).toBeTruthy()
  const tipTop = parseFloat(tip.style.top)
  const tipLeft = parseFloat(tip.style.left)
  const holeTop = parseFloat(hole.style.top)
  const holeLeft = parseFloat(hole.style.left)
  const holeW = parseFloat(hole.style.width)
  const holeH = parseFloat(hole.style.height)
  return {
    tip: { top: tipTop, left: tipLeft, bottom: tipTop + TIP_H, right: tipLeft + TIP_W },
    hole: { top: holeTop, left: holeLeft, bottom: holeTop + holeH, right: holeLeft + holeW },
  }
}

function overlaps(
  a: { top: number; left: number; bottom: number; right: number },
  b: { top: number; left: number; bottom: number; right: number },
): boolean {
  return !(a.right <= b.left || a.left >= b.right || a.bottom <= b.top || a.top >= b.bottom)
}

describe('TutorialOverlay: \u72ed\u5e45\u30fb\u6a2a\u753b\u9762\u3067\u3082\u5439\u304d\u51fa\u3057\u304c\u5bfe\u8c61\u3092\u96a0\u3055\u306a\u3044 (\u8981\u671b3)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
    document.body.innerHTML = ''
  })

  it('\u5e45390px (\u7e26) \u306e\u4e2d\u592e\u30dc\u30bf\u30f3\u3067\u5439\u304d\u51fa\u3057\u306f\u5bfe\u8c61\u306b\u91cd\u306a\u3089\u305a\u753b\u9762\u5185\u306b\u53ce\u307e\u308b', async () => {
    setViewport(390, 844)
    const { tip, hole } = await renderAndGetRects({ top: 400, left: 135, width: 120, height: 40 })
    expect(overlaps(tip, hole)).toBe(false)
    expect(tip.left).toBeGreaterThanOrEqual(8)
    expect(tip.right).toBeLessThanOrEqual(390 - 8)
  })

  it('\u6a2a\u753b\u9762 844x390 \u306e\u4e2d\u592e\u30dc\u30bf\u30f3\u3067\u5439\u304d\u51fa\u3057\u306f\u5bfe\u8c61\u306b\u91cd\u306a\u3089\u306a\u3044', async () => {
    setViewport(844, 390)
    const { tip, hole } = await renderAndGetRects({ top: 170, left: 360, width: 120, height: 40 })
    expect(overlaps(tip, hole)).toBe(false)
  })

  it('\u6a2a\u753b\u9762 844x390 \u306e\u5927\u304d\u306a\u5bfe\u8c61 (\u4e0a\u4e0b\u5de6\u53f3\u306b\u53ce\u307e\u3089\u306a\u3044) \u3067\u3082\u5439\u304d\u51fa\u3057\u306f\u5bfe\u8c61\u306b\u91cd\u306a\u3089\u306a\u3044', async () => {
    setViewport(844, 390)
    const { tip, hole } = await renderAndGetRects({ top: 120, left: 300, width: 240, height: 160 })
    expect(overlaps(tip, hole)).toBe(false)
  })

  it('\u6a2a\u753b\u9762 667x375 \u306e\u4e2d\u592e\u30dc\u30bf\u30f3\u3067\u3082\u5439\u304d\u51fa\u3057\u306f\u5bfe\u8c61\u306b\u91cd\u306a\u3089\u306a\u3044', async () => {
    setViewport(667, 375)
    const { tip, hole } = await renderAndGetRects({ top: 160, left: 270, width: 120, height: 40 })
    expect(overlaps(tip, hole)).toBe(false)
  })
})
