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
