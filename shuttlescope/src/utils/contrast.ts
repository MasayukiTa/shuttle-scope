/**
 * WCAG 2.x のコントラスト比計算 (純関数)。
 * ヒートマップのセル色と文字色の組み合わせが AA (通常文字 4.5:1) を満たすかを
 * テストで固定するために使う。画面側の色決定には使わない。
 */

export type Rgb = readonly [number, number, number]

/** '#rrggbb' を [r,g,b] (0-255) にする */
export function hexToRgb(hex: string): Rgb {
  const h = hex.replace('#', '')
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ]
}

/** 相対輝度 (WCAG) */
export function relativeLuminance([r, g, b]: Rgb): number {
  const lin = (v: number) => {
    const c = v / 255
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)
  }
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
}

/** 2 色のコントラスト比 (1〜21) */
export function contrastRatio(a: Rgb, b: Rgb): number {
  const la = relativeLuminance(a)
  const lb = relativeLuminance(b)
  const hi = Math.max(la, lb)
  const lo = Math.min(la, lb)
  return (hi + 0.05) / (lo + 0.05)
}

/** 前景 (alpha 付き) を背景に重ねた結果の色 */
export function blend(fg: Rgb, alpha: number, bg: Rgb): Rgb {
  return [
    Math.round(fg[0] * alpha + bg[0] * (1 - alpha)),
    Math.round(fg[1] * alpha + bg[1] * (1 - alpha)),
    Math.round(fg[2] * alpha + bg[2] * (1 - alpha)),
  ]
}
