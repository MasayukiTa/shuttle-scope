import { describe, it, expect } from 'vitest'
import {
  quadToUnit, unitToCell, isInsideQuad,
  fallbackTapToCell, calibratedTapToCell,
  type Quad,
} from '@/utils/courtHomography'

// 単位正方形 (= 軸平行・歪みなし) の四角形。TL,TR,BR,BL の順。
const unitQuad: Quad = [
  { x: 0, y: 0 },
  { x: 1, y: 0 },
  { x: 1, y: 1 },
  { x: 0, y: 1 },
]

describe('quadToUnit — 軸平行な四角形', () => {
  it('四隅がそのまま (u,v) の角に戻る', () => {
    // -0 と 0 を区別しないよう toBeCloseTo で比較する (値は数値的に正確)。
    const corners: Array<[number, number, number, number]> = [
      [0, 0, 0, 0], [1, 0, 1, 0], [1, 1, 1, 1], [0, 1, 0, 1],
    ]
    for (const [px, py, eu, ev] of corners) {
      const uv = quadToUnit(unitQuad, px, py)!
      expect(uv.u).toBeCloseTo(eu, 9)
      expect(uv.v).toBeCloseTo(ev, 9)
    }
  })

  it('中心は (0.5, 0.5)', () => {
    const uv = quadToUnit(unitQuad, 0.5, 0.5)!
    expect(uv.u).toBeCloseTo(0.5, 6)
    expect(uv.v).toBeCloseTo(0.5, 6)
  })
})

describe('quadToUnit — 斜め撮影で歪んだ四角形 (台形)', () => {
  // 奥 (上辺) が狭く手前 (下辺) が広い、よくある俯瞰アングル。
  const trapezoid: Quad = [
    { x: 0.30, y: 0.20 },
    { x: 0.70, y: 0.20 },
    { x: 0.90, y: 0.80 },
    { x: 0.10, y: 0.80 },
  ]

  it('四隅が角に戻る', () => {
    const expectedCorners = [
      { u: 0, v: 0 }, { u: 1, v: 0 }, { u: 1, v: 1 }, { u: 0, v: 1 },
    ]
    trapezoid.forEach((p, i) => {
      const uv = quadToUnit(trapezoid, p.x, p.y)!
      expect(uv.u).toBeCloseTo(expectedCorners[i].u, 5)
      expect(uv.v).toBeCloseTo(expectedCorners[i].v, 5)
    })
  })

  it('台形の重心付近は内側 (u,v in [0,1]) に戻り、中央マスに入る', () => {
    const cx = (0.30 + 0.70 + 0.90 + 0.10) / 4
    const cy = (0.20 + 0.20 + 0.80 + 0.80) / 4
    const uv = quadToUnit(trapezoid, cx, cy)!
    expect(uv.u).toBeCloseTo(0.5, 6)
    expect(uv.v).toBeCloseTo(0.5, 6)
    const cell = unitToCell(uv.u, uv.v)
    expect(cell).toEqual({ col: 1, row: 1 })
  })

  it('台形の外 (枠の外側) は範囲外と判定される', () => {
    expect(isInsideQuad(trapezoid, 0.5, 0.05)).toBe(false)
    expect(isInsideQuad(trapezoid, 0.5, 0.5)).toBe(true)
  })
})

describe('unitToCell — 3x3 への割り当て', () => {
  it('各マスの中心が正しい行・列になる', () => {
    expect(unitToCell(1 / 6, 1 / 6)).toEqual({ col: 0, row: 0 })
    expect(unitToCell(3 / 6, 3 / 6)).toEqual({ col: 1, row: 1 })
    expect(unitToCell(5 / 6, 5 / 6)).toEqual({ col: 2, row: 2 })
  })

  it('範囲外は端のマスへ丸める (死角を作らない)', () => {
    expect(unitToCell(-0.2, -0.2)).toEqual({ col: 0, row: 0 })
    expect(unitToCell(1.5, 1.5)).toEqual({ col: 2, row: 2 })
  })
})

describe('quadToUnit — 退化した四角形', () => {
  it('3 点が一直線でも例外を投げない', () => {
    const degenerate: Quad = [
      { x: 0, y: 0 }, { x: 0.5, y: 0 }, { x: 1, y: 0 }, { x: 0.5, y: 0.5 },
    ]
    const uv = quadToUnit(degenerate, 0.5, 0.1)
    expect(uv === null || Number.isFinite(uv.v)).toBe(true)
  })
})

// ─── fallbackTapToCell — 固定枠経路の «真ん中が選べない» 回帰ガード ──────────
describe('fallbackTapToCell — 枠外タップを捨てず端マスへ丸める', () => {
  it('枠内の中央は中央マス (1,1)', () => {
    expect(fallbackTapToCell(0.5, 0.5)).toEqual({ row: 1, col: 1 })
  })

  it('各マスの中心が正しい row/col になる', () => {
    expect(fallbackTapToCell(1 / 6, 1 / 6)).toEqual({ row: 0, col: 0 })
    expect(fallbackTapToCell(5 / 6, 5 / 6)).toEqual({ row: 2, col: 2 })
  })

  it('旧バグ回帰ガード: 枠外 (負・1超) でも null を返さず端マスへ丸める', () => {
    // 旧実装は nx/ny が [0,1] 外だと早期 return して «何も選べない» 死角を作り、
    // 撮影方向でコートが枠からずれると «真ん中あたりを選べない» 症状の原因だった。
    expect(fallbackTapToCell(-0.3, -0.3)).toEqual({ row: 0, col: 0 })
    expect(fallbackTapToCell(1.4, 1.4)).toEqual({ row: 2, col: 2 })
    expect(fallbackTapToCell(0.5, -0.1)).toEqual({ row: 0, col: 1 })
    expect(fallbackTapToCell(1.2, 0.5)).toEqual({ row: 1, col: 2 })
  })
})

// ─── calibratedTapToCell — 実コート四角形に沿った半面 3×3 割り当て ───────────
describe('calibratedTapToCell — 斜め撮影の台形でも中央を拾う', () => {
  // 奥が狭く手前が広い俯瞰アングル (quad 全体: v=0 奥ベースライン, v=1 手前ベースライン)。
  const trapezoid: Quad = [
    { x: 0.30, y: 0.20 },  // TL (奥左)
    { x: 0.70, y: 0.20 },  // TR (奥右)
    { x: 0.90, y: 0.80 },  // BR (手前右)
    { x: 0.10, y: 0.80 },  // BL (手前左)
  ]

  it('far 半面: 奥ベースライン際の中央タップは画面上段・中央列 (row0,col1)', () => {
    // v≈0 付近 (奥ベースライン) の中央。far は画面 row をそのまま使う。
    const cell = calibratedTapToCell(trapezoid, 0.5, 0.22, 'far')!
    expect(cell).toEqual({ row: 0, col: 1 })
  })

  it('near 半面: ネット〜手前側の «真ん中» が中央マス (row1,col1) に入る', () => {
    // near 半面 = v∈[0.5,1]。その中央 v≈0.75 付近 = 台形の下寄り中央。
    // 台形下辺中点は ((0.90+0.10)/2, 0.80)=(0.5,0.80)。その少し上を中央として拾う。
    const cell = calibratedTapToCell(trapezoid, 0.5, 0.65, 'near')!
    expect(cell.col).toBe(1)
    expect(cell.row).toBe(1)
  })

  it('列は画面基準で左=col0, 右=col2 (両半面とも鏡映しない)', () => {
    // 台形上辺 (奥) の左寄り・右寄り。
    const left = calibratedTapToCell(trapezoid, 0.33, 0.22, 'far')!
    const right = calibratedTapToCell(trapezoid, 0.67, 0.22, 'far')!
    expect(left.col).toBe(0)
    expect(right.col).toBe(2)
  })

  it('退化四角形では null を返す (例外を投げない)', () => {
    const degenerate: Quad = [
      { x: 0, y: 0 }, { x: 0.5, y: 0 }, { x: 1, y: 0 }, { x: 0.5, y: 0 },
    ]
    expect(calibratedTapToCell(degenerate, 0.5, 0.5, 'near')).toBeNull()
  })
})
