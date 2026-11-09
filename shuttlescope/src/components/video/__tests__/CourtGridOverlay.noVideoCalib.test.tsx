/**
 * T003-05: 映像なしモードのコートキャリブレーション。
 *
 * muse の実機確認 (F-T003-05) で、記録画面の設定タブの「キャリブレーションを
 * 開く」が映像なしモードでは何も開かなかった。修正 (NoVideoCalibCanvas) は
 * CourtGridOverlay を空の 16:9 キャンバスに載せ、動画フレームに依存せず正規化
 * 座標で 6 点を置けるようにする。本テストはその「映像が無くても校正できる作り」
 * が実際に成立することを、合成の静止キャンバス (動画なし) 上で確かめる。
 *
 * 仙台大学の要望 4 (撮る方向は人によって違う → 四隅合わせで校正) に関わるので、
 * 校正を最後まで完了できること、および校正後にコート外・範囲外をタップしても
 * 入力が落ちない (例外が出ず、確定済みの 6 点が壊れない) ことを検証する。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import { useRef } from 'react'
import { CourtGridOverlay } from '../CourtGridOverlay'

// backend は未設定 (404 相当) を返す。これで CourtGridOverlay は localStorage に
// も無ければ「未校正」と判定し、校正開始ボタンを出す (loadFailed=false)。
const apiGet = vi.fn()
vi.mock('@/api/client', () => ({
  API_BASE_URL: 'http://localhost:8765/api',
  apiGet: (...args: unknown[]) => apiGet(...args),
  fetchAuthed: vi.fn(() =>
    Promise.resolve(new Response('{}', { status: 200 })),
  ),
}))

// 404 を errorStatus(err) が拾えるよう status を持たせる。
function notFound(): Promise<never> {
  const err = Object.assign(new Error('not found'), { status: 404 })
  return Promise.reject(err)
}

const CANVAS_W = 1280
const CANVAS_H = 720

// 映像なしキャンバス相当: 16:9 のコンテナ div に CourtGridOverlay を載せる。
// NoVideoCalibCanvas が本番でやっているのと同じ構成を最小化したもの。
function NoVideoHarness({ onSaved }: { onSaved?: () => void }) {
  const ref = useRef<HTMLDivElement>(null)
  return (
    <div ref={ref} style={{ width: CANVAS_W, height: CANVAS_H }}>
      <CourtGridOverlay
        matchId="m1"
        containerRef={ref}
        visible
        onCalibrationSaved={onSaved}
      />
    </div>
  )
}

function getSvg(): SVGSVGElement {
  const svg = document.querySelector('svg')
  if (!svg) throw new Error('SVG overlay not rendered')
  return svg as unknown as SVGSVGElement
}

// コンテナ基準の正規化座標 (nx,ny) を clientX/clientY に直して pointerdown する。
function tapNorm(svg: SVGSVGElement, nx: number, ny: number) {
  fireEvent.pointerDown(svg, {
    clientX: nx * CANVAS_W,
    clientY: ny * CANVAS_H,
  })
}

// コート 4 隅 + ネット両端の 6 点 (0:TL 1:TR 2:BR 3:BL 4:NL 5:NR)。
const SIX_POINTS: Array<[number, number]> = [
  [0.2, 0.2],
  [0.8, 0.2],
  [0.85, 0.9],
  [0.15, 0.9],
  [0.18, 0.55],
  [0.82, 0.55],
]

let rectSpy: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  apiGet.mockReset()
  apiGet.mockImplementation(() => notFound())

  // jsdom は ResizeObserver を持たない。CourtGridOverlay が new する。
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  )

  // jsdom は getBoundingClientRect を全て 0 で返す。クリック→正規化座標の計算に
  // 実寸が要るので、SVG の矩形を 0,0 原点・CANVAS_W×CANVAS_H に固定する。
  rectSpy = vi
    .spyOn(SVGElement.prototype, 'getBoundingClientRect')
    .mockReturnValue({
      x: 0,
      y: 0,
      left: 0,
      top: 0,
      right: CANVAS_W,
      bottom: CANVAS_H,
      width: CANVAS_W,
      height: CANVAS_H,
      toJSON: () => ({}),
    } as DOMRect)

  // jsdom は setPointerCapture を実装しない (ドラッグ開始で呼ばれ得る)。
  if (!('setPointerCapture' in Element.prototype)) {
    // @ts-expect-error jsdom polyfill
    Element.prototype.setPointerCapture = () => {}
  }
})

afterEach(() => {
  rectSpy?.mockRestore()
  vi.unstubAllGlobals()
  cleanup()
})

describe('CourtGridOverlay — 映像なしモードの校正 (T003-05)', () => {
  it('映像が無くても校正開始ボタンが出る (導線が成立する)', async () => {
    render(<NoVideoHarness />)
    // backend 404 → localStorage も空 → 未校正 → 校正開始ボタンが現れる。
    const btn = await screen.findByRole('button', {
      name: /コートグリッド|グリッド|設定/,
    })
    expect(btn).toBeInTheDocument()
  })

  it('6 点を置くと校正が完了し localStorage に保存される', async () => {
    const onSaved = vi.fn()
    render(<NoVideoHarness onSaved={onSaved} />)

    const startBtn = await screen.findByRole('button', {
      name: /コートグリッド|グリッド|設定/,
    })
    fireEvent.click(startBtn)

    const svg = getSvg()
    for (const [nx, ny] of SIX_POINTS) {
      tapNorm(svg, nx, ny)
    }

    const raw = localStorage.getItem('court-calib-m1')
    expect(raw).not.toBeNull()
    const saved = JSON.parse(raw as string)
    expect(Array.isArray(saved)).toBe(true)
    expect(saved).toHaveLength(6)
    // 置いた正規化座標が保存されている (先頭点で確認)。
    expect(saved[0].x).toBeCloseTo(0.2, 5)
    expect(saved[0].y).toBeCloseTo(0.2, 5)
  })

  it('校正完了後にコート外・範囲外をタップしても入力が落ちない (要望4)', async () => {
    render(<NoVideoHarness />)

    const startBtn = await screen.findByRole('button', {
      name: /コートグリッド|グリッド|設定/,
    })
    fireEvent.click(startBtn)

    const svg = getSvg()
    for (const [nx, ny] of SIX_POINTS) {
      tapNorm(svg, nx, ny)
    }
    // 6 点確定済み。ここから先のタップは校正モード外なので無視されるべき。
    expect(JSON.parse(localStorage.getItem('court-calib-m1') as string)).toHaveLength(6)

    // コート外・キャンバス範囲外 (負値・1 超) を複数回タップ。例外が出ないこと。
    expect(() => {
      tapNorm(svg, -0.5, -0.5)
      tapNorm(svg, 1.5, 1.4)
      tapNorm(svg, 0.5, 0.5)
    }).not.toThrow()

    // 確定済みの 6 点は 7 点目が足されたりせず保たれている。
    const after = JSON.parse(localStorage.getItem('court-calib-m1') as string)
    expect(after).toHaveLength(6)
  })
})
