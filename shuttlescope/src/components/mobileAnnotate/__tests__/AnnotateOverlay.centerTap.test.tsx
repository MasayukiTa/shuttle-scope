/**
 * AnnotateOverlay — 実コンポーネント render + 座標クリック回帰テスト (STEP1 REPRODUCE)
 *
 * 「動画の真ん中を選べない」回帰を、純関数テスト (courtHomography.quad.test.ts) ではなく
 * 実際の AnnotateOverlay を render し、コンテナ座標を指定してクリックすることで
 * 再現・ガードする。jsdom は getBoundingClientRect() が全て 0 を返すため、
 * コンテナ・コート枠の rect をアスペクト比ごとにモックして座標クリックを成立させる。
 *
 * 検証項目:
 *  - キャリブ済 (courtQuad 指定) で、縦長(9:16)/横長(16:9)/正方(1:1) のいずれでも
 *    コート中央をクリックすると中央ゾーン MC が staged になる (死角なし)。
 *  - キャリブ無し (fallback 経路) でも固定枠中央クリックが MC になる。
 *  - 枠外 (コートのずっと外) タップは「何も選べない」死角にならず、端ゾーンへ丸められる。
 *  - staged 後に primary ボタンを押すと onCommit がそのゾーンで発火する。
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { AnnotateOverlay, type ZoneCode } from '../AnnotateOverlay'
import type { Quad } from '@/utils/courtHomography'

// react-i18next の t() はキーをそのまま返す (ゾーンラベルは zones.XX キー)。
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

// MIcon は material-symbols フォント依存なので軽量な span に差し替える。
vi.mock('@/components/common/MIcon', () => ({
  MIcon: ({ name }: { name: string }) => <span data-micon={name} />,
}))

// 正方/縦長/横長のコンテナサイズ。数値はピクセル。
const SIZES = {
  square:    { w: 600, h: 600 },
  portrait:  { w: 360, h: 640 },  // 9:16
  landscape: { w: 640, h: 360 },  // 16:9
}

// 台形 (奇 v=0 奧ベースライン / v=1 手前ベースライン)。正規座標。
const trapezoid: Quad = [
  { x: 0.30, y: 0.20 }, // TL
  { x: 0.70, y: 0.20 }, // TR
  { x: 0.90, y: 0.80 }, // BR
  { x: 0.10, y: 0.80 }, // BL
]

// quad の (u,v) を正規座標 (0..1) へ戻す双一次写像。
function bilerp(q: Quad, u: number, v: number): { x: number; y: number } {
  const top = { x: q[0].x + (q[1].x - q[0].x) * u, y: q[0].y + (q[1].y - q[0].y) * u }
  const bot = { x: q[3].x + (q[2].x - q[3].x) * u, y: q[3].y + (q[2].y - q[3].y) * u }
  return { x: top.x + (bot.x - top.x) * v, y: top.y + (bot.y - top.y) * v }
}

/**
 * jsdom で getBoundingClientRect() が 0 を返す問題を回避するため、render 後に
 * 対象要素の rect をモックする。courtQuad 有時は containerRef (flex-1 の div)、
 * 無時は courtRef (固定枠の div) が対象。どちらも (0,0)-(w,h) の rect として
 * 扱うことで、正規座標 nx=clientX/w, ny=clientY/h が成立する。
 */
function mockRect(el: Element, w: number, h: number) {
  ;(el as HTMLElement).getBoundingClientRect = () =>
    ({ left: 0, top: 0, right: w, bottom: h, width: w, height: h, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect
}

afterEach(() => cleanup())

describe('AnnotateOverlay — キャリブ済コートで中央タップが MC に入る (死角なし)', () => {
  for (const [name, size] of Object.entries(SIZES)) {
    it(`${name} (${size.w}x${size.h}): far 半面のコート中央タップ→ MC`, () => {
      const onCommit = vi.fn()
      const { container } = render(
        <AnnotateOverlay
          prompt="test"
          onCommit={onCommit}
          onCancel={() => {}}
          courtQuad={trapezoid}
          half="far"
        />,
      )
      // courtQuad 有時のタップ対象 = containerRef (onClick を持つ flex-1 div)。
      const target = container.querySelector('.flex-1') as HTMLElement
      expect(target).toBeTruthy()
      mockRect(target, size.w, size.h)

      // far 半面 (v∈[0,0.5]) の中央 v=0.25 あたり = コート中央。
      const p = bilerp(trapezoid, 0.5, 0.25)
      fireEvent.click(target, { clientX: p.x * size.w, clientY: p.y * size.h })

      // staged が MC になれば、下部の staged 表示 「→ MC」が出る。
      expect(container.textContent).toContain('→ MC')
    })
  }

  it('near 半面のコート中央タップ→ MC', () => {
    const { container } = render(
      <AnnotateOverlay prompt="test" onCommit={() => {}} onCancel={() => {}} courtQuad={trapezoid} half="near" />,
    )
    const target = container.querySelector('.flex-1') as HTMLElement
    mockRect(target, 600, 600)
    const p = bilerp(trapezoid, 0.5, 0.75) // near 半面 (v∈[0.5,1]) の中央
    fireEvent.click(target, { clientX: p.x * 600, clientY: p.y * 600 })
    expect(container.textContent).toContain('→ MC')
  })

  it('staged 後に primary を押すと onCommit が MC で発火', () => {
    const onCommit = vi.fn()
    const { container } = render(
      <AnnotateOverlay prompt="test" onCommit={onCommit} onCancel={() => {}} courtQuad={trapezoid} half="far" />,
    )
    const target = container.querySelector('.flex-1') as HTMLElement
    mockRect(target, 600, 600)
    const p = bilerp(trapezoid, 0.5, 0.25)
    fireEvent.click(target, { clientX: p.x * 600, clientY: p.y * 600 })
    // primary ボタン = auto.AnnotateOverlay.confirm ラベルのボタン。
    const commitBtn = screen.getByRole('button', { name: /confirm/ })
    fireEvent.click(commitBtn)
    expect(onCommit).toHaveBeenCalledWith('MC' as ZoneCode)
  })
})

describe('AnnotateOverlay — キャリブ無し (fallback 固定枠) でも中央タップが MC', () => {
  // courtRect 既定 = { x:0.15, y:0.10, w:0.70, h:0.70 }。固定枠内の中央は
  // 枠の (0.5,0.5) = ML/MC/MR の中央 MC。courtRef (absolute div) がタップ対象。
  it('固定枠中央クリック→ MC (枠外を捨てず割り当て)', () => {
    const { container } = render(
      <AnnotateOverlay prompt="test" onCommit={() => {}} onCancel={() => {}} />,
    )
    // fallback 時のタップ対象 = courtRef (grid を持つ absolute div)。grid の親。
    const grid = container.querySelector('.grid') as HTMLElement
    const courtEl = grid.parentElement as HTMLElement
    mockRect(courtEl, 700, 700)
    // 枠内正規座標 (0.5,0.5) = コート中央。courtEl 全体が枠なので 350,350。
    fireEvent.click(courtEl, { clientX: 350, clientY: 350 })
    expect(container.textContent).toContain('→ MC')
  })

  it('旧バグ回帰ガード: 枠のすっと外 (負座標) でも死角にならず端ゾーンへ丸める', () => {
    const { container } = render(
      <AnnotateOverlay prompt="test" onCommit={() => {}} onCancel={() => {}} />,
    )
    const grid = container.querySelector('.grid') as HTMLElement
    const courtEl = grid.parentElement as HTMLElement
    mockRect(courtEl, 700, 700)
    // 枠の左上外側 (nx<0, ny<0)。旧実装は早期 return で staged=null のまま死角。
    // 新実装は BL (左奇 row0,col0 → ZONE_GRID[0]='BL') へ丸める。
    fireEvent.click(courtEl, { clientX: -200, clientY: -200 })
    expect(container.textContent).toContain('→ BL')
  })
})
