/**
 * F-T003-05 回帰テスト: 映像なしモードのコートキャリブレーション画面が
 * 実際に描画され、校正を開始できることを検証する。
 *
 * 背景: 設定タブの「キャリブレーションを開く」は courtGridVisible=true にするだけで、
 * 映像なしモードの校正 UI は NoVideoCalibCanvas(→CourtGridOverlay) に集約されている。
 * 本テストはその NoVideoCalibCanvas を実コンポーネントとして描画し、
 * (1) 校正開始導線が DOM に出る (2) 開始すると 6 点配置ガイドに遷移する
 * ことを確かめる。左パネルが非表示(matchDay/mobile)でも機能することの根帹。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, fireEvent, waitFor } from '@testing-library/react'
import { createRef } from 'react'

// i18n: t() は defaultValue またはキー文字列をそのまま返す
const tFn = (k: string, o?: Record<string, unknown>) =>
  (o && typeof o.defaultValue === 'string') ? (o.defaultValue as string) : k
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: tFn, i18n: { language: 'ja', changeLanguage: vi.fn() } }),
  Trans: ({ children }: { children?: React.ReactNode }) => children ?? null,
  initReactI18next: { type: '3rdParty', init: vi.fn() },
}))

// court_calibration は未校正(空)を返す → 「キャリブレーション開始」導線が出る
const apiGetMock = vi.fn(async (_path: string) => ({ data: { points: [] } }))
vi.mock('@/api/client', () => ({
  apiGet: (p: string) => apiGetMock(p),
  fetchAuthed: vi.fn(async () => ({ ok: true, json: async () => ({}) })),
  API_BASE_URL: '',
}))

// CourtGridOverlay はコンテナサイズ監視に ResizeObserver を使うが jsdom には無い。
// 既存テスト(PlayMode.videoError 等)と同じ流儀でグローバルにスタブする。
vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })

import { NoVideoCalibCanvas } from '../AnnotatorPage'

function renderCanvas(onClose = vi.fn()) {
  const ref = createRef<HTMLDivElement>()
  const utils = render(
    <NoVideoCalibCanvas
      matchId="42"
      containerRef={ref}
      onClose={onClose}
      t={tFn}
    />,
  )
  return { ...utils, onClose }
}

beforeEach(() => {
  apiGetMock.mockClear()
  localStorage.clear()
})

describe('F-T003-05 映像なしキャリブレーション', () => {
  it('NoVideoCalibCanvas を描画すると CourtGridOverlay の校正開始導線が DOM に出る', async () => {
    const { getByText } = renderCanvas()
    // タイトル(映像なし)が出る
    expect(getByText('コートキャリブレーション（映像なし）')).toBeTruthy()
    // CourtGridOverlay が実マウントされ、未校正時の開始ボタン(key: auto.CourtGridOverlay.k1)が出る
    await waitFor(() => expect(getByText('auto.CourtGridOverlay.k1')).toBeTruthy())
  })

  it('校正開始を押すと 6 点配置ガイド(click_point)に遷移する', async () => {
    const { getByText } = renderCanvas()
    const startBtn = await waitFor(() => getByText('auto.CourtGridOverlay.k1'))
    fireEvent.click(startBtn)
    // calibrating → 次に置く点のガイドが出る
    await waitFor(() => expect(getByText('auto.CourtGridOverlay.click_point')).toBeTruthy())
  })

  it('閉じるボタンで onClose が呼ばれる', () => {
    const { getByText, onClose } = renderCanvas()
    fireEvent.click(getByText('閉じる'))
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
