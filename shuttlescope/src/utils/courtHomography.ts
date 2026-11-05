/**
 * courtHomography — フロントエンド用ホモグラフィユーティリティ
 *
 * バックエンドの court_calibration.py と同等の計算をブラウザで実行する。
 * 外部ライブラリ不要。
 */

export type H3x3 = number[][]  // 3×3 行列 (行優先)

/** 正規化座標 (x, y) にホモグラフィ H を適用して変換後の座標を返す。 */
export function applyHomography(H: H3x3, x: number, y: number): [number, number] {
  const w = H[2][0] * x + H[2][1] * y + H[2][2]
  return [
    (H[0][0] * x + H[0][1] * y + H[0][2]) / w,
    (H[1][0] * x + H[1][1] * y + H[1][2]) / w,
  ]
}

/** コート正規化座標 (cx, cy) → 18 ゾーン情報 */
export function courtCoordToZone(cx: number, cy: number): {
  courtX:   number
  courtY:   number
  zoneId:   number   // 0-17  (row*3 + col)
  zoneName: string   // "A_front_left" など
  side:     'A' | 'B'
  depth:    'front' | 'mid' | 'back'
  col:      'left' | 'center' | 'right'
} {
  const clampedX = Math.max(0, Math.min(1, cx))
  const clampedY = Math.max(0, Math.min(1, cy))

  const colI = Math.min(Math.floor(clampedX * 3), 2)
  const rowI = Math.min(Math.floor(clampedY * 6), 5)

  const colNames:   ('left' | 'center' | 'right')[] = ['left', 'center', 'right']
  const depthNames: ('front' | 'mid' | 'back')[]    = ['front', 'mid', 'back']
  const side = rowI < 3 ? 'A' : 'B'

  return {
    courtX:   Math.round(clampedX * 10000) / 10000,
    courtY:   Math.round(clampedY * 10000) / 10000,
    zoneId:   rowI * 3 + colI,
    zoneName: `${side}_${depthNames[rowI % 3]}_${colNames[colI]}`,
    side,
    depth:    depthNames[rowI % 3],
    col:      colNames[colI],
  }
}

/**
 * 画像正規化座標 → コート正規化座標 → 18 ゾーン情報。
 * H は POST /api/matches/{id}/court_calibration レスポンスの data.homography。
 */
export function pixelNormToZone(H: H3x3, xNorm: number, yNorm: number) {
  const [cx, cy] = applyHomography(H, xNorm, yNorm)
  return courtCoordToZone(cx, cy)
}

/**
 * 点 (x, y) がコート多角形の内側にあるかを Ray casting で判定。
 * polygon: [[x,y], ...] 正規化座標の頂点リスト（コーナー4点など）
 */
export function isInsideCourt(x: number, y: number, polygon: [number, number][]): boolean {
  const n = polygon.length
  let inside = false
  let j = n - 1
  for (let i = 0; i < n; i++) {
    const [xi, yi] = polygon[i]
    const [xj, yj] = polygon[j]
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) {
      inside = !inside
    }
    j = i
  }
  return inside
}

// ─── 四角形バイリニア逆写像 ───────────────────────────────────────────────
//
// コート 4 隅 (TL, TR, BR, BL) で囲まれた四角形の内側のタップ点 (px, py) を、
// その四角形を単位正方形 [0,1]×[0,1] に写したときの座標 (u, v) に戻す。
//
//   u: TL→TR 方向 (= コート左→右)。TL,BL 辺で 0、TR,BR 辺で 1
//   v: TL→BL 方向 (= コート上辺→下辺)。TL,TR 辺で 0、BL,BR 辺で 1
//
// なぜホモグラフィでなくバイリニアか:
//   打点・着地の入力は「どのマスを選んだか」という 3×3 の粗い判定で足りる。
//   バイリニア写像は凸四角形なら必ず 1 つの解を持ち、外部ライブラリも行列分解も
//   要らず、撮影方向 (正面・斜め・後方・横) が変わって四角形が歪んでも、4 隅さえ
//   指定されていれば内部を素直に 3×3 に割れる。真の透視補正が必要な CV 側は
//   引き続きバックエンドのホモグラフィを使う（こちらは入力 UI 専用）。

export type Quad = [Point2, Point2, Point2, Point2]  // TL, TR, BR, BL
export type Point2 = { x: number; y: number }

/**
 * 双一次写像 P(u,v) = (1-u)(1-v)·TL + u(1-v)·TR + uv·BR + (1-u)v·BL の逆。
 * 返り値 (u, v) は四角形の内側なら [0,1]²。外側は範囲外の値になる
 * (呼び出し側がクランプ/範囲判定して使う)。四角形が退化している場合は null。
 */
export function quadToUnit(quad: Quad, px: number, py: number): { u: number; v: number } | null {
  const [tl, tr, br, bl] = quad
  // P(u,v) = tl + u·(tr-tl) + v·(bl-tl) + u·v·(tl - tr + br - bl)
  const ax = tr.x - tl.x
  const ay = tr.y - tl.y
  const bx = bl.x - tl.x
  const by = bl.y - tl.y
  const cx = tl.x - tr.x + br.x - bl.x
  const cy = tl.y - tr.y + br.y - bl.y
  const dx = px - tl.x
  const dy = py - tl.y

  // v について 2 次方程式 A·v² + B·v + C = 0 を解く (u を消去)。
  //   (dx − v·bx)(ay + v·cy) − (dy − v·by)(ax + v·cx) = 0 を展開した係数。
  const A = cx * by - cy * bx
  const B = cy * dx - cx * dy + ax * by - ay * bx
  const C = ay * dx - ax * dy

  // v が決まれば u は一意に決まる。v の候補ごとに u も復元し、(u,v) が最も
  // [0,1]² に収まる組を選ぶ。こうしないと二次方程式のもう一方の根 (射影の
  // 対称点) を誤って拾い、内部点なのに u,v が負になることがある。
  const solveU = (vv: number): number | null => {
    const denomX = ax + cx * vv
    const denomY = ay + cy * vv
    if (Math.abs(denomX) >= Math.abs(denomY)) {
      if (Math.abs(denomX) < 1e-12) return null
      return (dx - bx * vv) / denomX
    }
    if (Math.abs(denomY) < 1e-12) return null
    return (dy - by * vv) / denomY
  }
  // (u,v) が単位正方形からどれだけ外れているか (内側なら 0)。
  const outside = (u: number, vv: number): number => {
    const du = Math.max(0, -u, u - 1)
    const dv = Math.max(0, -vv, vv - 1)
    return du + dv
  }

  const vCandidates: number[] = []
  if (Math.abs(A) < 1e-9) {
    // 平行四辺形 (c≈0) なら線形。B≈0 は退化四角形。
    if (Math.abs(B) < 1e-12) return null
    vCandidates.push(-C / B)
  } else {
    const disc = B * B - 4 * A * C
    if (disc < 0) return null
    const sq = Math.sqrt(disc)
    vCandidates.push((-B + sq) / (2 * A))
    vCandidates.push((-B - sq) / (2 * A))
  }

  let best: { u: number; v: number } | null = null
  let bestScore = Infinity
  for (const vv of vCandidates) {
    const u = solveU(vv)
    if (u === null || !Number.isFinite(u) || !Number.isFinite(vv)) continue
    const score = outside(u, vv)
    if (score < bestScore) {
      bestScore = score
      best = { u, v: vv }
    }
  }
  return best
}

/** 3×3 グリッドの行・列へ割り当てる (0..2)。範囲外は端のマスへ丸める。 */
export function unitToCell(u: number, v: number): { col: number; row: number } {
  const col = Math.min(2, Math.max(0, Math.floor(u * 3)))
  const row = Math.min(2, Math.max(0, Math.floor(v * 3)))
  return { col, row }
}

/**
 * タップ点 (px, py, 動画正規化座標) が四角形の内側か。ライン上を落とさない
 * 余裕 tol を持つ。quadToUnit が null (退化) のときは false。
 */
export function isInsideQuad(quad: Quad, px: number, py: number, tol = 0.02): boolean {
  const uv = quadToUnit(quad, px, py)
  if (!uv) return false
  return uv.u >= -tol && uv.u <= 1 + tol && uv.v >= -tol && uv.v <= 1 + tol
}

// ─── タップ点 → 3×3 セル (入力 UI の中核ロジック) ──────────────────────────
//
// AnnotateOverlay のタップ判定を純関数として切り出したもの。コンポーネント内の
// クロージャに埋めると単体テストできず、「動画の中央あたりを選べない」回帰を
// 検出できないため、ここに置いてユニットテストで守る。

/** コート半面。'near'=手前(ネット〜手前ベースライン), 'far'=奥(ネット〜奥ベースライン)。 */
export type CourtHalf = 'near' | 'far'

/**
 * フォールバック経路: キャリブ四角形が無いとき、固定枠内の正規化座標 (nx, ny)
 * を 3×3 セルへ割り当てる。
 *
 * 旧実装は `if (nx<0||nx>1||ny<0||ny>1) return` で枠外タップを «捨てて» いた。
 * 撮影方向によって動画内のコートが固定枠からずれると、コート中央をタップしても
 * この早期 return に当たって «何も選べない» のが「真ん中あたりを選択できない」
 * 症状の原因だった。ここでは枠外を捨てず端マスへ丸める (死角を作らない)。
 */
export function fallbackTapToCell(nx: number, ny: number): { row: number; col: number } {
  const col = Math.min(2, Math.max(0, Math.floor(nx * 3)))
  const row = Math.min(2, Math.max(0, Math.floor(ny * 3)))
  return { row, col }
}

/**
 * キャリブ経路: 実コート四角形 quad と半面 half を使い、コンテナ正規化座標
 * (px, py) を «その半面の» 3×3 セル (画面並びの row/col) へ割り当てる。
 * 退化四角形などで逆写像できないときは null。
 *
 * row は «画面上の並び» (0=上, 2=下)。ZONE_GRID の意味ラベル (back/mid/net) への
 * 読み替えは呼び出し側が half に応じて行う (far はそのまま, near は 2-row)。
 */
export function calibratedTapToCell(
  quad: Quad, px: number, py: number, half: CourtHalf,
): { row: number; col: number } | null {
  const uv = quadToUnit(quad, px, py)
  if (!uv) return null
  const col = Math.min(2, Math.max(0, Math.floor(uv.u * 3)))
  // コート全体の v (0=奥ベースライン側, 1=手前ベースライン側, ネット=0.5) を
  // 指定半面内に再正規化してから 3 分割する。
  const vLocal = half === 'far' ? uv.v / 0.5 : (uv.v - 0.5) / 0.5
  const row = Math.min(2, Math.max(0, Math.floor(vLocal * 3)))
  return { row, col }
}
