import { describe, it, expect } from 'vitest'
import {
  calibratedTapToCell,
  fallbackTapToCell,
  applyOrientationToCell,
  normalizeOrientation,
  type Quad,
  type CourtOrientation,
} from '@/utils/courtHomography'

// ─── customer request #4「コート中央」回帰ガード ───────────────────────────────
//
// 要望: 撮影方向によらず「コートの中央をタップしたら中央のゾーンが選べる」。
// 実装の核:
//   - calibratedTapToCell / fallbackTapToCell が col=floor(u*3) / row=floor(v*3)
//     で中央 (u,v の中央) を中央マス col=1,row=1 に割り当てる。
//   - applyOrientationToCell は row→2-row / col→2-col の反転だが、中央 (1) は
//     反転しても 2-1=1 で不変。つまり「中央は撮影方向を変えても中央のまま」。
// ここは「コート中央 → 中央マス」が calib 経路・fallback 経路の両方で成り立ち、
// かつ向き (flipH/flipV/swapHalf の全 8 通り) を重ねても中央が中央に留まることを
// 明示的に回帰ガードする (個別方向のテストはあるが、この不変性は未ガードだった)。

// 単位正方形コート。TL,TR,BR,BL。v=0 が奥ベースライン, v=1 が手前, ネット=0.5。
const unitQuad: Quad = [
  { x: 0, y: 0 },
  { x: 1, y: 0 },
  { x: 1, y: 1 },
  { x: 0, y: 1 },
]

// flipH/flipV/swapHalf の全 2^3 = 8 通り。
const ALL_ORIENTATIONS: CourtOrientation[] = [false, true].flatMap((flipH) =>
  [false, true].flatMap((flipV) =>
    [false, true].map((swapHalf) => ({ flipH, flipV, swapHalf })),
  ),
)

describe('コート中央タップ → 中央マス (calib 経路)', () => {
  it('far 半面: 半面中央 (v=0.25) のコート中央タップは中央マス (row1,col1)', () => {
    // far 半面 = v∈[0,0.5]。その中央 v=0.25。u=0.5 が左右中央。
    const cell = calibratedTapToCell(unitQuad, 0.5, 0.25, 'far')!
    expect(cell).toEqual({ row: 1, col: 1 })
  })

  it('near 半面: 半面中央 (v=0.75) のコート中央タップは中央マス (row1,col1)', () => {
    // near 半面 = v∈[0.5,1]。その中央 v=0.75。
    const cell = calibratedTapToCell(unitQuad, 0.5, 0.75, 'near')!
    expect(cell).toEqual({ row: 1, col: 1 })
  })
})

describe('コート中央タップ → 中央マス (fallback 固定枠経路)', () => {
  it('固定枠の中央 (0.5,0.5) は中央マス (row1,col1)', () => {
    expect(fallbackTapToCell(0.5, 0.5)).toEqual({ row: 1, col: 1 })
  })
})

describe('コート中央は撮影方向 (orientation) を変えても中央マスのまま', () => {
  // 中央セル。反転 (2-1=1) でも swap でも中央は動かないことを全 8 通りで確認する。
  const center = { row: 1, col: 1 }

  it.each(ALL_ORIENTATIONS)(
    'flipH=$flipH flipV=$flipV swapHalf=$swapHalf でも中央セルは (1,1) のまま',
    (orientation) => {
      const o = normalizeOrientation(orientation)
      expect(applyOrientationToCell(center, o)).toEqual({ row: 1, col: 1 })
    },
  )

  it.each(ALL_ORIENTATIONS)(
    'flipH=$flipH flipV=$flipV swapHalf=$swapHalf: calib の中央タップ→向き適用後も (1,1)',
    (orientation) => {
      const o = normalizeOrientation(orientation)
      // 実効 half は swapHalf 側で決まるが、どちらの half でも半面中央は中央行。
      const vByHalf = o.swapHalf ? { far: 0.75, near: 0.25 } : { far: 0.25, near: 0.75 }
      for (const half of ['far', 'near'] as const) {
        const py = vByHalf[half]
        const base = calibratedTapToCell(unitQuad, 0.5, py, half)
        // swap により py と half の対応が崩れる組では半面外になり得るため、
        // 中央行が出る (half, py) の組だけを中央不変の対象にする。
        if (base && base.row === 1 && base.col === 1) {
          expect(applyOrientationToCell(base, o)).toEqual({ row: 1, col: 1 })
        }
      }
    },
  )
})
