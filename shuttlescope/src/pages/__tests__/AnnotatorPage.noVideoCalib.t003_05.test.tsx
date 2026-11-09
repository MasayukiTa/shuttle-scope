import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import React, { createRef } from 'react'
import i18n from '@/i18n'

// court_calibration は backend 未存在（404）を返し、映像なしでも
// ローカルで校正が成立することを検証する。
const err404 = Object.assign(new Error('not found'), { status: 404 })
vi.mock('@/api/client', () => ({
  apiGet: vi.fn(() => Promise.reject(err404)),
  apiPost: vi.fn(),
  fetchAuthed: vi.fn(() => Promise.resolve({ ok: true, text: () => Promise.resolve('') } as Response)),
  API_BASE_URL: 'http://localhost:8765/api',
}))

// jsdom に ResizeObserver が無いため stub。
class RO { observe() {} unobserve() {} disconnect() {} }
;(globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = RO

// jsdom@29 に PointerEvent が無い。clientX/Y を保持する最小 polyfill。
if (typeof (globalThis as { PointerEvent?: unknown }).PointerEvent === 'undefined') {
  class PointerEventPolyfill extends MouseEvent {
    constructor(type: string, params: PointerEventInit = {}) {
      super(type, params)
    }
  }
  ;(globalThis as unknown as { PointerEvent: unknown }).PointerEvent = PointerEventPolyfill
}

import { NoVideoCalibCanvas } from '../AnnotatorPage'

const MATCH_ID = '4242'
const STORAGE_KEY = `court-calib-${MATCH_ID}`

function renderCanvas() {
  const ref = createRef<HTMLDivElement>() as React.RefObject<HTMLDivElement>
  // containerRef は NoVideoCalibCanvas 内部の div に付くが、寸法は jsdom で 0。
  // getBoundingClientRect を stub して点配置の clientX/Y が正規化されるようにする。
  return render(
    <NoVideoCalibCanvas
      matchId={MATCH_ID}
      containerRef={ref}
      onClose={() => {}}
      t={i18n.t.bind(i18n)}
    />,
  )
}

describe('NoVideoCalibCanvas (T003-05: 映像なしモードの校正画面)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    i18n.changeLanguage('ja')
  })

  it('映像が無くても校正画面（タイトル・ヒント・設定ボタン）が開く', async () => {
    renderCanvas()
    expect(screen.getByText('コートキャリブレーション（映像なし）')).toBeInTheDocument()
    expect(
      screen.getByText(/映像が無くても、コートの 4 隅/),
    ).toBeInTheDocument()
    // 既存校正が無い（404）ので、校正開始ボタンが出る。
    await waitFor(() => {
      expect(screen.getByText('コートグリッドを設定')).toBeInTheDocument()
    })
  })

  it('映像なしで 6点を置いて校正が localStorage に保存される', async () => {
    const { container } = renderCanvas()
    const startBtn = await screen.findByText('コートグリッドを設定')
    fireEvent.click(startBtn)
    const svg = container.querySelector('svg') as SVGSVGElement
    expect(svg).toBeTruthy()
    // getBoundingClientRect を 400x225 に stub（正規化座標算出用）
    svg.getBoundingClientRect = () => ({ left: 0, top: 0, width: 400, height: 225, right: 400, bottom: 225, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect
    const coords = [ [40,30],[360,30],[360,200],[40,200],[40,115],[360,115] ]
    for (const [cx, cy] of coords) {
      fireEvent.pointerDown(svg, { clientX: cx, clientY: cy })
    }
    await waitFor(() => {
      const saved = localStorage.getItem(STORAGE_KEY)
      expect(saved).toBeTruthy()
      expect(JSON.parse(saved as string)).toHaveLength(6)
    })
  })
})
