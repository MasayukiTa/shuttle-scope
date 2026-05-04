// 統計ユーティリティ
// 有限値のみを対象にピアソン相関係数を計算する

export function pearson(xs: number[], ys: number[]): number | null {
  if (!Array.isArray(xs) || !Array.isArray(ys)) return null
  const n = Math.min(xs.length, ys.length)
  if (n < 2) return null
  let sx = 0
  let sy = 0
  let sxx = 0
  let syy = 0
  let sxy = 0
  let count = 0
  for (let i = 0; i < n; i++) {
    const x = xs[i]
    const y = ys[i]
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue
    sx += x
    sy += y
    sxx += x * x
    syy += y * y
    sxy += x * y
    count++
  }
  if (count < 2) return null
  const meanX = sx / count
  const meanY = sy / count
  const varX = sxx / count - meanX * meanX
  const varY = syy / count - meanY * meanY
  const cov = sxy / count - meanX * meanY
  const denom = Math.sqrt(varX * varY)
  if (!Number.isFinite(denom) || denom === 0) return null
  return cov / denom
}

/** 平均（null / 非有限値を除外）。サンプル無しなら null。 */
export function mean(xs: Array<number | null | undefined>): number | null {
  const arr: number[] = []
  for (const v of xs) {
    if (v == null) continue
    if (typeof v !== 'number' || !Number.isFinite(v)) continue
    arr.push(v)
  }
  if (arr.length === 0) return null
  let s = 0
  for (const v of arr) s += v
  return s / arr.length
}

/** 標本標準偏差 (分母 n-1)。有効値 n<2 の場合は null。 */
export function sampleStd(xs: Array<number | null | undefined>): number | null {
  const arr: number[] = []
  for (const v of xs) {
    if (v == null) continue
    if (typeof v !== 'number' || !Number.isFinite(v)) continue
    arr.push(v)
  }
  if (arr.length < 2) return null
  let s = 0
  for (const v of arr) s += v
  const m = s / arr.length
  let sq = 0
  for (const v of arr) sq += (v - m) * (v - m)
  return Math.sqrt(sq / (arr.length - 1))
}

// 数値配列の z-score 正規化（母集団標準偏差使用）。std=0 のとき 0 ベクトルを返す。
export function zScore(xs: number[]): number[] {
  const n = xs.length
  if (n === 0) return []
  let s = 0
  for (const v of xs) s += v
  const m = s / n
  let sq = 0
  for (const v of xs) sq += (v - m) * (v - m)
  const std = Math.sqrt(sq / n)
  if (!Number.isFinite(std) || std === 0) return xs.map(() => 0)
  return xs.map((v) => (v - m) / std)
}

// 行列（行=サンプル, 列=変数）から共分散行列（列×列）を返す。
export function covMatrix(matrix: number[][]): number[][] {
  const n = matrix.length
  if (n === 0) return []
  const p = matrix[0].length
  const means = new Array(p).fill(0)
  for (const row of matrix) for (let j = 0; j < p; j++) means[j] += row[j]
  for (let j = 0; j < p; j++) means[j] /= n
  const cov: number[][] = Array.from({ length: p }, () => new Array(p).fill(0))
  for (const row of matrix) {
    for (let i = 0; i < p; i++) {
      for (let j = 0; j < p; j++) {
        cov[i][j] += (row[i] - means[i]) * (row[j] - means[j])
      }
    }
  }
  const denom = Math.max(1, n - 1)
  for (let i = 0; i < p; i++) for (let j = 0; j < p; j++) cov[i][j] /= denom
  return cov
}

// 累乗法で上位 k 個の固有ベクトル/固有値を抽出（対称行列用, deflation）
export function powerIterationPCA(
  cov: number[][],
  k: number,
  opts: { maxIter?: number; tol?: number } = {},
): { vectors: number[][]; values: number[] } {
  const maxIter = opts.maxIter ?? 500
  const tol = opts.tol ?? 1e-8
  const p = cov.length
  if (p === 0) return { vectors: [], values: [] }
  // deep copy
  const A = cov.map((row) => row.slice())
  const vectors: number[][] = []
  const values: number[] = []
  for (let c = 0; c < Math.min(k, p); c++) {
    let v = new Array(p).fill(0).map((_, i) => Math.sin(i + c + 1) + 0.1)
    // normalize
    let norm = Math.sqrt(v.reduce((s, x) => s + x * x, 0))
    if (norm === 0) norm = 1
    v = v.map((x) => x / norm)
    let lambda = 0
    for (let iter = 0; iter < maxIter; iter++) {
      const w = new Array(p).fill(0)
      for (let i = 0; i < p; i++) {
        let sum = 0
        for (let j = 0; j < p; j++) sum += A[i][j] * v[j]
        w[i] = sum
      }
      const wn = Math.sqrt(w.reduce((s, x) => s + x * x, 0))
      if (!Number.isFinite(wn) || wn === 0) break
      const vNext = w.map((x) => x / wn)
      let diff = 0
      for (let i = 0; i < p; i++) diff += Math.abs(vNext[i] - v[i])
      v = vNext
      const newLambda = wn
      if (Math.abs(newLambda - lambda) < tol && diff < tol) {
        lambda = newLambda
        break
      }
      lambda = newLambda
    }
    // Rayleigh quotient for sign/value accuracy
    let rq = 0
    for (let i = 0; i < p; i++) {
      let s = 0
      for (let j = 0; j < p; j++) s += A[i][j] * v[j]
      rq += v[i] * s
    }
    vectors.push(v)
    values.push(rq)
    // deflation: A <- A - lambda v v^T
    for (let i = 0; i < p; i++) {
      for (let j = 0; j < p; j++) A[i][j] -= rq * v[i] * v[j]
    }
  }
  return { vectors, values }
}
