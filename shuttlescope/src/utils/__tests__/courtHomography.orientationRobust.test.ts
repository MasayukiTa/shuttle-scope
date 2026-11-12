import { describe, it, expect } from 'vitest'
import {
  calibratedTapToCell,
  calibratedTapToCellClamped,
  fallbackTapToCell,
  fallbackTapToCellClamped,
  quadToUnit,
  type Quad,
} from '@/utils/courtHomography'

// ─── 要望#4-3「撃影の向きが違う場合を想定して、校正したあと、枠の外や端をタップしても入力が落ちないか」回帰ガード ───
//
// 既存の courtHomography.quad.test.ts / orientationCenter.test.ts は
// 「コート中央・左右端が正しいマスに入る」「丸めの clamped が正しい」を
// 守る。ここで守るのは別の観点 —— 「撃影方向がどうであれ、校正後に画面の
// どこ（枠内・枠外・場外・極端座標）をタップしても、入力経路が「落ちない」」こと。
//
// 「落ちない」の契約（コードの実装に合わせた定義）：
//   (A) どの関数も throw しない（例外で UI がクラッシュしない）。
//   (B) calibratedTapToCell(Clamped) の返り値は「有効セル(row/col∈{0,1,2}) または null」の
//       いずれか。null は「射影できない点（枠の遠い外側・退化）」の正当な結果で、
//       呼び出し側はこのとき固定枠フォールバックに落ちる（= 落ちない）。
//       中途半端な NaN/±Infinity/範囲外セルを 「返してはならない」。
//   (C) 最終防線の fallbackTapToCell(Clamped) は、あらゆる座標（枠外・極端含む）で
//       必ず有効セルを返す（null なし）。calib が null でも UI はこちらで入力を続けられる。
//
// なぜ null を許容するか：斜め撃影の台形では、コートの「遠い枠外」には元の射影が
// 及ばず逆写像の解が存在しない（判別式 < 0）。quadToUnit はそこで null を返すのが正しく、
// calibratedTapToCell も null を返す。これは「落ちる」ではなく「固定枠に落とす合図」なので、
// 本テストは null を失敗扱いにせず、(B)(C) の契約で「落ちない」を保証する。

const isCell = (c: { row: number; col: number } | null | undefined): boolean =>
  !!c &&
  Number.isInteger(c.row) && Number.isInteger(c.col) &&
  c.row >= 0 && c.row <= 2 && c.col >= 0 && c.col <= 2

const isCellOrNull = (c: { row: number; col: number } | null): boolean =>
  c === null || isCell(c)

// 撃影 4+ 方向の典型的な正常四角形（quad.test.ts と同じ並び：TL,TR,BR,BL）。
const QUADS: Array<{ name: string; quad: Quad }> = [
  { name: '正面', quad: [
    { x: 0.30, y: 0.20 }, { x: 0.70, y: 0.20 },
    { x: 0.90, y: 0.80 }, { x: 0.10, y: 0.80 },
  ] },
  { name: '斜め', quad: [
    { x: 0.35, y: 0.18 }, { x: 0.78, y: 0.25 },
    { x: 0.82, y: 0.78 }, { x: 0.12, y: 0.82 },
  ] },
  { name: '後方', quad: [
    { x: 0.10, y: 0.20 }, { x: 0.90, y: 0.20 },
    { x: 0.70, y: 0.80 }, { x: 0.30, y: 0.80 },
  ] },
  { name: '横', quad: [
    { x: 0.15, y: 0.35 }, { x: 0.80, y: 0.25 },
    { x: 0.85, y: 0.65 }, { x: 0.20, y: 0.75 },
  ] },
  { name: '縦長', quad: [
    { x: 0.25, y: 0.12 }, { x: 0.75, y: 0.12 },
    { x: 0.88, y: 0.88 }, { x: 0.12, y: 0.88 },
  ] },
  { name: '横長', quad: [
    { x: 0.20, y: 0.35 }, { x: 0.80, y: 0.35 },
    { x: 0.92, y: 0.65 }, { x: 0.08, y: 0.65 },
  ] },
]

// 画面上の「あらゆる場所」：枠内(0.5付近)・四辺(0/1)・角・外側(負・1超)。
const GRID = [-0.5, -0.1, 0, 0.001, 0.25, 0.5, 0.75, 0.999, 1, 1.1, 1.5]
const TAPS: Array<[number, number]> = []
for (const px of GRID) for (const py of GRID) TAPS.push([px, py])

describe('要望#4-3: calib 経路は全タップで throw せず、有効セルか null を返す', () => {
  for (const { name, quad } of QUADS) {
    for (const half of ['near', 'far'] as const) {
      it(`${name} / ${half}: 全タップで 例外なし・返り値は有効セル(0..2)か null`, () => {
        for (const [px, py] of TAPS) {
          const cell = calibratedTapToCell(quad, px, py, half)
          const picked = calibratedTapToCellClamped(quad, px, py, half)
          // 中途半端な範囲外セル/NaN を返さない（null は許容）。
          expect(isCellOrNull(cell)).toBe(true)
          expect(isCellOrNull(picked)).toBe(true)
          // clamped を返す場合は真偽値（undefined/NaN でない）。
          if (picked !== null) expect(typeof picked.clamped).toBe('boolean')
        }
      })
    }
  }
})

describe('要望#4-3: 最終防線 fallback はあらゆる座標で必ず有効セルを返す（null なし）', () => {
  // calib が null になる点（斜め撃影の遠い枠外など）でも、UI はこちらで入力を続けられる。
  it('枠外・極端を含む全タップで 有効セル(0..2)、例外なし', () => {
    for (const [px, py] of TAPS) {
      expect(isCell(fallbackTapToCell(px, py))).toBe(true)
      const picked = fallbackTapToCellClamped(px, py)
      expect(isCell(picked)).toBe(true)
      expect(typeof picked.clamped).toBe('boolean')
    }
  })
})

describe('要望#4-3: 非有限・NaN の异常座標でも throw しない', () => {
  // タッチ座標が何らかの拍子で NaN / Infinity になっても、入力 UI がクラッシュしないこと。
  const WEIRD: Array<[number, number]> = [
    [Number.NaN, 0.5], [0.5, Number.NaN], [Number.NaN, Number.NaN],
    [Number.POSITIVE_INFINITY, 0.5], [0.5, Number.NEGATIVE_INFINITY],
    [Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY],
  ]
  const quad = QUADS[0].quad
  it('calibrated: 异常座標で throw せず、有効セルか null', () => {
    for (const [px, py] of WEIRD) {
      const run = () => calibratedTapToCell(quad, px, py, 'far')
      expect(run).not.toThrow()
      expect(isCellOrNull(run())).toBe(true)
    }
  })
  it('fallback: 异常座標で throw しない', () => {
    for (const [px, py] of WEIRD) {
      expect(() => fallbackTapToCell(px, py)).not.toThrow()
    }
  })
  it('quadToUnit: 枠外タップでも u,v は有限値か null（NaN/Infinity を返さない）', () => {
    for (const { quad } of QUADS) {
      for (const [px, py] of [[-0.3, -0.3], [1.4, 1.4], [0.5, 1.2], [-0.2, 0.5]] as Array<[number, number]>) {
        const uv = quadToUnit(quad, px, py)
        expect(uv === null || (Number.isFinite(uv.u) && Number.isFinite(uv.v))).toBe(true)
      }
    }
  })
})
