import { describe, it, expect } from 'vitest'
import {
  quadToUnit, unitToCell, isInsideQuad,
  fallbackTapToCell, calibratedTapToCell,
  courtQuadFromCalibPoints, inferCourtHalfFromCalibPoints,
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

// ─── courtQuadFromCalibPoints — 保存済み 6 点から courtQuad を取り出す ────────
describe('courtQuadFromCalibPoints', () => {
  // localStorage に保存される形: [TL, TR, BR, BL, NL, NR] (正規化座標)。
  const sixPoints = [
    { x: 0.30, y: 0.20 }, // TL
    { x: 0.70, y: 0.20 }, // TR
    { x: 0.90, y: 0.80 }, // BR
    { x: 0.10, y: 0.80 }, // BL
    { x: 0.20, y: 0.50 }, // NL (ネット左)
    { x: 0.80, y: 0.50 }, // NR (ネット右)
  ]

  it('先頭 4 点 (コート 4 隅) を Quad として返す', () => {
    const quad = courtQuadFromCalibPoints(sixPoints)
    expect(quad).not.toBeNull()
    expect(quad).toEqual(sixPoints.slice(0, 4))
  })

  it('4 点ちょうど (ネット無し) でも Quad を返す', () => {
    const quad = courtQuadFromCalibPoints(sixPoints.slice(0, 4))
    expect(quad).not.toBeNull()
  })

  it('未校正 (null / 非配列 / 点不足) は null', () => {
    expect(courtQuadFromCalibPoints(null)).toBeNull()
    expect(courtQuadFromCalibPoints(undefined)).toBeNull()
    expect(courtQuadFromCalibPoints('court-calib')).toBeNull()
    expect(courtQuadFromCalibPoints([{ x: 0, y: 0 }, { x: 1, y: 0 }, { x: 1, y: 1 }])).toBeNull()
  })

  it('壊れた座標 (NaN / 数値以外) を含む先頭 4 点は null', () => {
    const bad = [
      { x: 0.3, y: 0.2 }, { x: Number.NaN, y: 0.2 },
      { x: 0.9, y: 0.8 }, { x: 0.1, y: 0.8 },
    ]
    expect(courtQuadFromCalibPoints(bad)).toBeNull()
    const bad2 = [
      { x: 0.3, y: 0.2 }, { x: '0.7', y: 0.2 },
      { x: 0.9, y: 0.8 }, { x: 0.1, y: 0.8 },
    ]
    expect(courtQuadFromCalibPoints(bad2)).toBeNull()
  })

  it('退化配置 (4 隅が共線) は null → 呼び出し側は固定枠に落ちる', () => {
    const collinear = [
      { x: 0, y: 0 }, { x: 0.33, y: 0 }, { x: 0.66, y: 0 }, { x: 1, y: 0 },
    ]
    expect(courtQuadFromCalibPoints(collinear)).toBeNull()
  })

  it('返した Quad は calibratedTapToCell にそのまま渡せる (中央→中央マス)', () => {
    const quad = courtQuadFromCalibPoints(sixPoints)!
    // 台形の重心付近 = コート中央。near 半面の中央あたりを拾う。
    const cell = calibratedTapToCell(quad, 0.5, 0.65, 'near')
    expect(cell).not.toBeNull()
    expect(cell!.col).toBe(1)
  })
})

// ─── inferCourtHalfFromCalibPoints — ネット位置から near/far を推定 ───────────
describe('inferCourtHalfFromCalibPoints — 撮影方向で入力片面の写り方が変わる', () => {
  // 俯瞰: 奥が狭く手前が広い。ネットはコート中ほど〜上 (y 小) に写る → far。
  it('俯瞰 (ネットが 4 隅重心より上) は far', () => {
    const pts = [
      { x: 0.30, y: 0.20 }, { x: 0.70, y: 0.20 }, // 奥ベースライン
      { x: 0.90, y: 0.80 }, { x: 0.10, y: 0.80 }, // 手前ベースライン
      { x: 0.25, y: 0.45 }, { x: 0.75, y: 0.45 }, // ネット (重心 y=0.5 より上)
    ]
    expect(inferCourtHalfFromCalibPoints(pts)).toBe('far')
  })

  // 選手背後から手前ベースライン越しに撮る等: ネットが画面下寄り (y 大) → near。
  it('ネットが 4 隅重心より下 (手前に写る) は near', () => {
    const pts = [
      { x: 0.30, y: 0.20 }, { x: 0.70, y: 0.20 },
      { x: 0.90, y: 0.80 }, { x: 0.10, y: 0.80 },
      { x: 0.25, y: 0.65 }, { x: 0.75, y: 0.65 }, // ネット (重心 y=0.5 より下)
    ]
    expect(inferCourtHalfFromCalibPoints(pts)).toBe('near')
  })

  it('ネット 2 点が無い / 壊れている / 点不足のときは既定 far', () => {
    expect(inferCourtHalfFromCalibPoints(null)).toBe('far')
    expect(inferCourtHalfFromCalibPoints([{ x: 0, y: 0 }])).toBe('far')
    const netBroken = [
      { x: 0.3, y: 0.2 }, { x: 0.7, y: 0.2 }, { x: 0.9, y: 0.8 }, { x: 0.1, y: 0.8 },
      { x: Number.NaN, y: 0.5 }, { x: 0.75, y: 0.5 },
    ]
    expect(inferCourtHalfFromCalibPoints(netBroken)).toBe('far')
  })
})

// ─── calibratedTapToCell — 撮影 4 方向の台形でも中央/端を正しく拾う ───────────
// 配線の目的は «撮影方向が変わっても動画のコート上を直接タップで選べる» こと。
// 各方向で «コート中央タップ→中央列» «左右端→col0/col2» を回帰ガードする。
describe('calibratedTapToCell — 撮影 4 方向で中央と左右端を拾う', () => {
  // (1) 正面やや俯瞰: 奥狭・手前広の対称台形。
  const front: Quad = [
    { x: 0.30, y: 0.20 }, { x: 0.70, y: 0.20 },
    { x: 0.90, y: 0.80 }, { x: 0.10, y: 0.80 },
  ]
  // (2) 斜め (右寄りアングル): 右側が圧縮された非対称四角形。
  const diagonal: Quad = [
    { x: 0.35, y: 0.18 }, { x: 0.78, y: 0.25 },
    { x: 0.82, y: 0.78 }, { x: 0.12, y: 0.82 },
  ]
  // (3) 後方 (反対エンドから): 上下が入れ替わり手前が狭く奥が広い。
  const behind: Quad = [
    { x: 0.10, y: 0.20 }, { x: 0.90, y: 0.20 },
    { x: 0.70, y: 0.80 }, { x: 0.30, y: 0.80 },
  ]
  // (4) 横 (サイドライン側から): コートが横長に倒れ、左右が奥/手前になる平行四辺形。
  const side: Quad = [
    { x: 0.15, y: 0.35 }, { x: 0.80, y: 0.25 },
    { x: 0.85, y: 0.65 }, { x: 0.20, y: 0.75 },
  ]

  // quad の (u,v) パラメタ上で «半面中央・左右端» を作り、画面座標へ戻してタップする。
  // これにより «どの方向でも、コート自身の中央/左右端を指せば中央列/端列に入る» を
  // 方向非依存に検証できる (画面 x の大小ではなく、コート幾何に沿う)。
  const bilerp = (q: Quad, u: number, v: number) => {
    const top = { x: q[0].x + (q[1].x - q[0].x) * u, y: q[0].y + (q[1].y - q[0].y) * u }
    const bot = { x: q[3].x + (q[2].x - q[3].x) * u, y: q[3].y + (q[2].y - q[3].y) * u }
    return { x: top.x + (bot.x - top.x) * v, y: top.y + (bot.y - top.y) * v }
  }

  const cases: Array<{ name: string; quad: Quad }> = [
    { name: '正面', quad: front },
    { name: '斜め', quad: diagonal },
    { name: '後方', quad: behind },
    { name: '横', quad: side },
  ]

  for (const { name, quad } of cases) {
    it(`${name}: far 半面のコート中央タップは中央列 (col1)`, () => {
      const p = bilerp(quad, 0.5, 0.25) // far 半面 (v∈[0,0.5]) の中央あたり
      const cell = calibratedTapToCell(quad, p.x, p.y, 'far')!
      expect(cell.col).toBe(1)
      expect(cell.row).toBe(1)
    })

    it(`${name}: near 半面のコート中央タップは中央列 (col1)`, () => {
      const p = bilerp(quad, 0.5, 0.75) // near 半面 (v∈[0.5,1]) の中央あたり
      const cell = calibratedTapToCell(quad, p.x, p.y, 'near')!
      expect(cell.col).toBe(1)
      expect(cell.row).toBe(1)
    })

    it(`${name}: コート左端→col0 / 右端→col2 (u の順序を保つ)`, () => {
      const left = bilerp(quad, 1 / 6, 0.25)
      const right = bilerp(quad, 5 / 6, 0.25)
      expect(calibratedTapToCell(quad, left.x, left.y, 'far')!.col).toBe(0)
      expect(calibratedTapToCell(quad, right.x, right.y, 'far')!.col).toBe(2)
    })
  }
})
