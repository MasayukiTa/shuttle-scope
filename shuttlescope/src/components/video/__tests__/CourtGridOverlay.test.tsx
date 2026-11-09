import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { createRef } from 'react'

import { CourtGridOverlay } from '../CourtGridOverlay'
import * as apiClient from '@/api/client'

// F-T003-05: 映像なしモードでもコート校正（4隅＋ネット2点）を開始・保存できることを、
// 合成データ（固定の正規化座標）だけで検証する。実在の試合動画・静止画は使わない。
// CourtGridOverlay は映像非依存（コンテナ上の SVG に点を置く）ため、空のコンテナへ
// マウントするだけで校正ロジックが走る。

vi.mock('@/api/client', () => ({
  apiGet: vi.fn(),
  API_BASE_URL: 'http://localhost:8765/api',
  fetchAuthed: vi.fn(),
}))

const MATCH_ID = 'syn-vid-001'
const STORAGE_KEY = `court-calib-${MATCH_ID}`

// JSDOM は getBoundingClientRect を 0 で返す。校正クリックの座標計算は rect に依存
// するが、点の「個数」は rect に依存せず加算されるため 6 点到達で保存が走る。
// グリッド描画の見た目ではなく「校正を開始でき、6 点で保存される」ことを検証する。
function renderOverlay(onSaved?: () => void) {
  const ref = createRef<HTMLDivElement>()
  const utils = render(
    <div ref={ref} style={{ width: 640, height: 360 }}>
      <CourtGridOverlay
        matchId={MATCH_ID}
        containerRef={ref}
        visible={true}
        onCalibrationSaved={onSaved}
      />
    </div>,
  )
  return { ref, ...utils }
}

// 合成の 6 点（正規化座標）。TL, TR, BR, BL, Net-L, Net-R の順。
const SYNTH_POINTS: Array<[number, number]> = [
  [0.12, 0.20],
  [0.88, 0.20],
  [0.95, 0.90],
  [0.05, 0.90],
  [0.10, 0.55],
  [0.90, 0.55],
]

describe('CourtGridOverlay (映像なしモードの校正)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    try { localStorage.clear() } catch { /* ignore */ }
    // backend に補正が無い状態（points 空）を resolve で返す → loadFailed にならず
    // 「未校正 → 校正開始ボタン」の状態になる。
    vi.mocked(apiClient.apiGet).mockResolvedValue({ data: { points: [] } } as never)
    // 保存先 backend は常に成功を返す。
    vi.mocked(apiClient.fetchAuthed).mockResolvedValue({
      ok: true,
      status: 200,
      text: () => Promise.resolve(''),
    } as never)
  })

  it('映像なしでも校正を開始でき、6点クリックで localStorage に保存され onCalibrationSaved が呼ばれる', async () => {
    const onSaved = vi.fn()
    const { container } = renderOverlay(onSaved)

    // 初期は未校正の案内ボタン（校正開始）が出る。
    const startBtn = await waitFor(() => {
      const btn = container.querySelector('button')
      expect(btn).not.toBeNull()
      return btn as HTMLButtonElement
    })

    await act(async () => {
      fireEvent.click(startBtn)
    })

    // 校正モードに入ると SVG がクリックを受け付ける。
    const svg = await waitFor(() => {
      const el = container.querySelector('svg')
      expect(el).not.toBeNull()
      return el as SVGSVGElement
    })

    // 合成の 6 点を順にクリックして配置する。
    for (const [nx, ny] of SYNTH_POINTS) {
      await act(async () => {
        fireEvent.pointerDown(svg, { clientX: nx * 640, clientY: ny * 360 })
      })
    }

    // 6 点目で localStorage に 6 点保存される。
    await waitFor(() => {
      const saved = localStorage.getItem(STORAGE_KEY)
      expect(saved).not.toBeNull()
      const pts = JSON.parse(saved as string)
      expect(Array.isArray(pts)).toBe(true)
      expect(pts).toHaveLength(6)
    })

    // backend への保存成功で onCalibrationSaved が呼ばれる。
    await waitFor(() => {
      expect(onSaved).toHaveBeenCalled()
    })
    expect(apiClient.fetchAuthed).toHaveBeenCalled()
  })

  it('既に6点が保存済みなら visible=true でコートグリッド線が描画される（校正後にコートが使える）', async () => {
    // 事前に合成の 6 点を localStorage に用意。backend は points 空を返すため
    // フォールバックは走らないが、保存済みを読む経路の代わりに描画側を検証するため
    // ここでは backend 側から 6 点を返して backend 経由で校正済みにする。
    vi.mocked(apiClient.apiGet).mockResolvedValue({ data: { points: SYNTH_POINTS } } as never)

    const { container } = renderOverlay()

    // 6 点が入ると SVG に line 要素（グリッド）が描画される。
    await waitFor(() => {
      const lines = container.querySelectorAll('svg line')
      expect(lines.length).toBeGreaterThan(0)
    })
  })
})
