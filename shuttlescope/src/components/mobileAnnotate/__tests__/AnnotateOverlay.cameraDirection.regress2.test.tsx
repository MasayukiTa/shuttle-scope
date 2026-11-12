/**
 * AnnotateOverlay — 撮影方向 (camera direction) 別のコート中央タップ回帰テスト
 *
 * 既存の AnnotateOverlay.centerTap.test.tsx は「正面やや俯瞰」の台形
 * (奥が狭く手前が広い) だけを扱う。しかしcustomer の要望 4-3 は
 * 「撮影方向が正面・斜め・後方・横のどれでも、動画に写った
 * コートの «真ん中» をそのままタップして選べる」こと。このテストは
 * 実コンポーネントを render し、後方アングル (上下が入れ替わる台形) と
 * 横アングル (サイドライン側からの平行四辺形) の courtQuad でも、
 * コート中央タップが中央マス MC に入ることをガードする。
 *
 * 純関数テスト (courtHomography.quad.test.ts) は quad → cell の写像だけを守るが、
 * AnnotateOverlay の half 別ロウ読み (far は cell.row そのまま、near は 2-row) を
 * 含む結線は守られていない。ここで実 render してその結線を固定する。
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { AnnotateOverlay, type ZoneCode } from '../AnnotateOverlay'
import type { Quad } from '@/utils/courtHomography'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('@/components/common/MIcon', () => ({
  MIcon: ({ name }: { name: string }) => <span data-micon={name} />,
}))

const SIZES = {
  square:    { w: 600, h: 600 },
  portrait:  { w: 360, h: 640 },  // 9:16
  landscape: { w: 640, h: 360 },  // 16:9
}

// 正面やや俯瞰: 奥 (上辺) が狭く手前 (下辺) が広い。(既存テストと同じ基準)
const frontTrapezoid: Quad = [
  { x: 0.30, y: 0.20 }, // TL
  { x: 0.70, y: 0.20 }, // TR
  { x: 0.90, y: 0.80 }, // BR
  { x: 0.10, y: 0.80 }, // BL
]

// 後方 (反対エンドから): 上下が入れ替わり手前 (上辺) が狭く奥 (下辺) が広い。
// 四隠 TL/TR/BR/BL は常に「コートの TL/TR/BR/BL」を指すので、後方から撮ると
// 画面上では上辺 (TL-TR) が広く下辺 (BL-BR) が狭い形になる。
const rearTrapezoid: Quad = [
  { x: 0.10, y: 0.20 }, // TL
  { x: 0.90, y: 0.20 }, // TR
  { x: 0.70, y: 0.80 }, // BR
  { x: 0.30, y: 0.80 }, // BL
]

// 横 (サイドライン側から): コートが横長に倒れた平行四辺形。
// TL→TR (コート左→右) が画面では概ね縦方向、TL→BL (奥→手前) が横方向。
const sideParallelogram: Quad = [
  { x: 0.20, y: 0.15 }, // TL
  { x: 0.35, y: 0.75 }, // TR
  { x: 0.80, y: 0.85 }, // BR
  { x: 0.65, y: 0.25 }, // BL
]

// quad の (u,v) を正規座標 (0..1) へ戻す双一次写像。
function bilerp(q: Quad, u: number, v: number): { x: number; y: number } {
  const top = { x: q[0].x + (q[1].x - q[0].x) * u, y: q[0].y + (q[1].y - q[0].y) * u }
  const bot = { x: q[3].x + (q[2].x - q[3].x) * u, y: q[3].y + (q[2].y - q[3].y) * u }
  return { x: top.x + (bot.x - top.x) * v, y: top.y + (bot.y - top.y) * v }
}

function mockRect(el: Element, w: number, h: number) {
  ;(el as HTMLElement).getBoundingClientRect = () =>
    ({ left: 0, top: 0, right: w, bottom: h, width: w, height: h, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect
}

function tapAt(container: HTMLElement, w: number, h: number, nx: number, ny: number) {
  const target = container.querySelector('.flex-1') as HTMLElement
  expect(target).toBeTruthy()
  mockRect(target, w, h)
  fireEvent.click(target, { clientX: nx * w, clientY: ny * h })
}

afterEach(() => cleanup())

// far 半面: コート全体 v∈[0,0.5] を 3 分割。v=0.25 が far 半面の中央行。
// near 半面: v∈[0.5,1]。v=0.75 が near 半面の中央行。
// u=0.5 が左右の中央列。どちらの半面でも«その半面の真ん中»は MC。
describe('AnnotateOverlay — 撮影方向が変わってもコート中央タップは MC (far 半面) (resubmit)', () => {
  const cases: Array<{ name: string; quad: Quad }> = [
    { name: '正面やや俯瞰',       quad: frontTrapezoid },
    { name: '後方 (反対エンド)',    quad: rearTrapezoid },
    { name: '横 (サイドライン側)', quad: sideParallelogram },
  ]
  for (const { name, quad } of cases) {
    for (const [sizeName, size] of Object.entries(SIZES)) {
      it(`${name} / ${sizeName} (${size.w}x${size.h}): far 中央→ MC`, () => {
        const { container } = render(
          <AnnotateOverlay
            prompt="test"
            onCommit={() => {}}
            onCancel={() => {}}
            courtQuad={quad}
            half="far"
          />,
        )
        const p = bilerp(quad, 0.5, 0.25)
        tapAt(container, size.w, size.h, p.x, p.y)
        expect(container.textContent).toContain('\u2192 MC')
      })
    }
  }
})

describe('AnnotateOverlay — 撮影方向が変わってもコート中央タップは MC (near 半面)', () => {
  const cases: Array<{ name: string; quad: Quad }> = [
    { name: '後方 (反対エンド)',    quad: rearTrapezoid },
    { name: '横 (サイドライン側)', quad: sideParallelogram },
  ]
  for (const { name, quad } of cases) {
    it(`${name}: near 中央→ MC`, () => {
      const { container } = render(
        <AnnotateOverlay prompt="test" onCommit={() => {}} onCancel={() => {}} courtQuad={quad} half="near" />,
      )
      const p = bilerp(quad, 0.5, 0.75)
      tapAt(container, 600, 600, p.x, p.y)
      expect(container.textContent).toContain('\u2192 MC')
    })
  }
})

describe('AnnotateOverlay — 撮影方向別でも奥ベースライン際・ネット際の行が正しく分かれる', () => {
  // far 半面は cell.row をそのまま使う。v≈0 (奥ベースライン際) は奥行 = B*。
  // v≈0.5 直前 (ネット際) は far 半面の手前行 = N*。撮影方向が変わっても
  // quad に合わせて写像されるので、後方/横でも奥とネットの割り当ては崩れない。
  for (const { name, quad } of [
    { name: '後方', quad: rearTrapezoid },
    { name: '横',   quad: sideParallelogram },
  ]) {
    it(`${name}: far 半面 奥ベースライン際中央→ BC`, () => {
      const { container } = render(
        <AnnotateOverlay prompt="test" onCommit={() => {}} onCancel={() => {}} courtQuad={quad} half="far" />,
      )
      const p = bilerp(quad, 0.5, 0.04) // 奥ベースライン際 (v≈0) の中央列
      tapAt(container, 600, 600, p.x, p.y)
      expect(container.textContent).toContain('\u2192 BC')
    })
    it(`${name}: far 半面 ネット際中央→ NC`, () => {
      const { container } = render(
        <AnnotateOverlay prompt="test" onCommit={() => {}} onCancel={() => {}} courtQuad={quad} half="far" />,
      )
      const p = bilerp(quad, 0.5, 0.46) // ネット際 (v≈0.5直前) の中央列
      tapAt(container, 600, 600, p.x, p.y)
      expect(container.textContent).toContain('\u2192 NC')
    })
  }
})

describe('AnnotateOverlay — 撮影方向別で staged 後の確定がそのゾーンで発火', () => {
  it('横アングル: far 中央タップ→確定で onCommit(MC)', () => {
    const onCommit = vi.fn()
    const { container } = render(
      <AnnotateOverlay prompt="test" onCommit={onCommit} onCancel={() => {}} courtQuad={sideParallelogram} half="far" />,
    )
    const p = bilerp(sideParallelogram, 0.5, 0.25)
    tapAt(container, 600, 600, p.x, p.y)
    const commitBtn = screen.getByRole('button', { name: /confirm/ })
    fireEvent.click(commitBtn)
    expect(onCommit).toHaveBeenCalledWith('MC' as ZoneCode)
  })
})
