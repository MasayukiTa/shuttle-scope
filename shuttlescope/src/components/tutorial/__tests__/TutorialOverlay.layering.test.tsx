import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render } from '@testing-library/react'

vi.mock('@/api/client', () => ({ apiPost: vi.fn().mockResolvedValue({}), apiGet: vi.fn() }))
vi.mock('@/utils/analytics', () => ({ trackTutorialStep: vi.fn() }))
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string, o?: { defaultValue?: string }) => o?.defaultValue ?? k }),
}))

import { TutorialOverlay } from '../TutorialOverlay'

// \u8981\u671b3 \u306e\u6838\u5fc3: \u30c1\u30e5\u30fc\u30c8\u30ea\u30a2\u30eb\u306e\u6697\u5e55\u30fb\u5439\u304d\u51fa\u3057\u30fb\u30ea\u30f3\u30b0\u304c
// \u30a2\u30d7\u30ea\u306e\u901a\u5e38\u30e2\u30fc\u30c0\u30eb (z-[200] / z-[210]) \u3088\u308a\u524d\u9762\u306b\u3042\u308a\u3001
// \u300c\u88cf\u306b\u56de\u3089\u306a\u3044\u300d\u3053\u3068\u3092 z-index \u5024\u3067\u56fa\u5b9a\u3059\u308b\u56de\u5e30\u30c6\u30b9\u30c8\u3002
// \u30a2\u30d7\u30ea\u5185\u306e\u6700\u5927\u30e2\u30fc\u30c0\u30eb z-index (Notice \u306e z-[210])\u3002
// \u3053\u308c\u3088\u308a\u30c1\u30e5\u30fc\u30c8\u30ea\u30a2\u30eb\u304c\u524d\u9762\u306b\u306a\u3044\u3068 \u300c\u88cf\u306b\u56de\u308b\u300d\u3002
const APP_MODAL_MAX_Z = 210

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

// className \u306e Tailwind z-[NNN] \u30af\u30e9\u30b9\u304b\u3089\u6570\u5024\u3092\u62bd\u51fa\u3059\u308b\u3002
function zFromClass(el: Element | null): number | null {
  if (!el) return null
  const m = (el as HTMLElement).className.match(/z-\[(\d+)\]/)
  return m ? Number(m[1]) : null
}

describe('TutorialOverlay: \u30aa\u30fc\u30d0\u30fc\u30ec\u30a4\u304c\u4ed6\u8981\u7d20\u306e\u88cf\u306b\u56de\u3089\u306a\u3044 (\u8981\u671b3)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    Object.defineProperty(window, 'innerWidth', { value: 1024, configurable: true })
    Object.defineProperty(window, 'innerHeight', { value: 768, configurable: true })
  })
  afterEach(() => {
    vi.useRealTimers()
    document.body.innerHTML = ''
  })

  async function renderSpotlight() {
    placeTarget({ top: 300, left: 400, width: 120, height: 40 })
    const r = render(<TutorialOverlay tutorial={tutorial as never} onClose={() => {}} />)
    await act(async () => { vi.advanceTimersByTime(400) })
    return r
  }

  it('\u5439\u304d\u51fa\u3057\u672c\u4f53\u306e z-index \u306f\u30a2\u30d7\u30ea\u30e2\u30fc\u30c0\u30eb\u3088\u308a\u524d\u9762 (z-[302] > 210)', async () => {
    const { container } = await renderSpotlight()
    const tip = container.querySelector('.tutorial-tooltip-attention')
    const z = zFromClass(tip)
    expect(z).not.toBeNull()
    expect(z as number).toBeGreaterThan(APP_MODAL_MAX_Z)
  })

  it('\u5439\u304d\u51fa\u3057\u30b3\u30f3\u30c6\u30ca\u306e z-index \u3082\u30a2\u30d7\u30ea\u30e2\u30fc\u30c0\u30eb\u3088\u308a\u524d\u9762 (z-[300] > 210)', async () => {
    const { container } = await renderSpotlight()
    // \u6697\u5e55\u3092\u5305\u3080 fixed inset-0 \u30b3\u30f3\u30c6\u30ca (Spotlight \u306e\u89aa)\u3002
    const hole = container.querySelector('.tutorial-spotlight-hole')
    expect(hole).toBeTruthy()
    const containerDiv = hole?.parentElement
    const z = zFromClass(containerDiv ?? null)
    expect(z).not.toBeNull()
    expect(z as number).toBeGreaterThan(APP_MODAL_MAX_Z)
  })

  it('\u5916\u5074\u30af\u30ea\u30c3\u30af\u5438\u53ce\u67a0\u306e z-index \u304c\u30a2\u30d7\u30ea\u30e2\u30fc\u30c0\u30eb\u3088\u308a\u524d\u9762 (= 300 > 210)', async () => {
    const { container } = await renderSpotlight()
    // inline style \u3067 zIndex \u3092\u6301\u3064 fixed \u67a0 (\u30af\u30ea\u30c3\u30af\u5438\u53ce 4 \u679a)\u3002
    const framed = Array.from(container.querySelectorAll<HTMLElement>('div.fixed')).filter(
      (d) => d.style.zIndex !== '',
    )
    expect(framed.length).toBeGreaterThanOrEqual(4)
    for (const d of framed) {
      expect(Number(d.style.zIndex)).toBeGreaterThan(APP_MODAL_MAX_Z)
    }
  })
})
