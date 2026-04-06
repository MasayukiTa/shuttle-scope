/**
 * ShuttleScope 統一カラーシステム
 *
 * ルール:
 *   1. ヒートマップ・密度・連続値    → coolwarm スケール（CW_*）を使う
 *   2. 勝敗・正負のセマンティック    → WIN / LOSS を使う（coolwarm 端点と同じ色）
 *   3. 単系列の棒グラフ              → BAR を使う（coolwarm 低端の薄青）
 *   4. 複合チャートの折れ線          → LINE を使う（coolwarm 高端寄りのサーモン）
 *   5. 複数カテゴリの識別            → CATS を使う（coolwarm を等間隔で 4 色サンプリング）
 *   6. 散布・ツールチップ背景など    → SURFACE / BORDER を使う
 *
 * NG: amber / cyan / purple / green など独自色を個別コンポーネントに書かない
 */

// ── Coolwarm スケール（matplotlib 実値） ──────────────────────────────────────
/** 0.00 — 深青 (cold)  */
export const CW_MIN  = '#3b4cc0'
/** 0.25 — 薄青         */
export const CW_LOW  = '#8db0fe'
/** 0.50 — 白/ニュートラル */
export const CW_MID  = '#dddddd'
/** 0.75 — サーモン     */
export const CW_HIGH = '#f38a64'
/** 1.00 — 深赤 (hot)   */
export const CW_MAX  = '#b40426'

/** coolwarm 5 制御点（補間用） */
export const CW_STOPS: [number, number, number][] = [
  [59,  76,  192],   // 0.00
  [141, 176, 254],   // 0.25
  [221, 221, 221],   // 0.50
  [243, 138, 100],   // 0.75
  [180,   4,  38],   // 1.00
]

/** 0–1 の値を coolwarm RGB 文字列に変換（線形補間） */
export function coolwarm(ratio: number, alpha = 1): string {
  const t = Math.max(0, Math.min(1, ratio))
  const seg = Math.min(Math.floor(t * 4), 3)
  const u = t * 4 - seg
  const [r1, g1, b1] = CW_STOPS[seg]
  const [r2, g2, b2] = CW_STOPS[seg + 1]
  const r = Math.round(r1 + (r2 - r1) * u)
  const g = Math.round(g1 + (g2 - g1) * u)
  const b = Math.round(b1 + (b2 - b1) * u)
  return alpha < 1 ? `rgba(${r},${g},${b},${alpha})` : `rgb(${r},${g},${b})`
}

// ── セマンティック ─────────────────────────────────────────────────────────────
/** 勝ち / プラス / 良好 — coolwarm 低端（青） */
export const WIN  = CW_MIN   // '#3b4cc0'
/** 負け / マイナス / 要改善 — coolwarm 高端（赤） */
export const LOSS = CW_MAX   // '#b40426'

// ── 単系列・コンボチャート ────────────────────────────────────────────────────
/** 単系列の棒グラフ（coolwarm 薄青） */
export const BAR  = CW_LOW   // '#8db0fe'
/** 複合チャートの折れ線・アクセント（coolwarm サーモン） */
export const LINE = CW_HIGH  // '#f38a64'

// ── カテゴリカル（複数系列の識別） ─────────────────────────────────────────────
/** coolwarm を 4 点でサンプリングしたカテゴリカル配色 */
export const CATS = [CW_MIN, CW_LOW, CW_HIGH, CW_MAX] as const
// '#3b4cc0', '#8db0fe', '#f38a64', '#b40426'

/** n 番目のカテゴリ色を返す（ループ） */
export function catColor(i: number): string {
  return CATS[i % CATS.length]
}

// ── 密度・頻度ヒートマップ用（白→深青）────────────────────────────────────────
/**
 * 密度/頻度ヒートマップ専用スケール。
 * 0 = 白(活動なし)、1 = 深青(高頻度)。
 * coolwarm(diverging)と異なり中央に意味のある中立色がない単方向データに使う。
 */
export function seqBlue(ratio: number): string {
  const t = Math.max(0, Math.min(1, ratio))
  // (240,244,255) = 白に近い薄青 → (59,76,192) = 深青
  const r = Math.round(240 - (240 - 59) * t)
  const g = Math.round(244 - (244 - 76) * t)
  const b = Math.round(255 - (255 - 192) * t)
  return `rgb(${r},${g},${b})`
}

// ── パフォーマンス指標用（高=青=良い, 低=赤=悪い）────────────────────────────
/**
 * 勝率・パフォーマンス指標用スケール。coolwarm を逆転させて使う。
 * rate=1.0(高勝率) → 深青(良い)、rate=0.5 → 白(中立)、rate=0.0 → 深赤(悪い)。
 * 「青=良い」の統一ルールに準拠。
 */
export function perfColor(rate: number, alpha = 1): string {
  return coolwarm(1 - Math.max(0, Math.min(1, rate)), alpha)
}

// ── UI サーフェス ─────────────────────────────────────────────────────────────
export const TOOLTIP_BG     = '#1f2937'
export const TOOLTIP_BORDER = '#374151'
export const AXIS_TICK      = '#9ca3af'
export const AXIS_TICK_LIGHT = '#475569'   // ライトモード用軸ラベル色
export const AXIS_LABEL     = '#6b7280'
export const CURSOR_FILL    = 'rgba(255,255,255,0.04)'

/** 共通ツールチップスタイル（Recharts contentStyle 用、ダークモード） */
export const TOOLTIP_STYLE = {
  backgroundColor: TOOLTIP_BG,
  border: `1px solid ${TOOLTIP_BORDER}`,
  borderRadius: '6px',
  color: '#f9fafb',
  fontSize: 12,
} as const

/** モード対応ツールチップスタイルを返す */
export function getTooltipStyle(isLight: boolean) {
  return isLight
    ? { backgroundColor: '#f8fafc', border: '1px solid #cbd5e1', borderRadius: '6px', color: '#0f172a', fontSize: 12 }
    : TOOLTIP_STYLE
}

// ── ライトモード対応ユーティリティ ─────────────────────────────────────────────

/**
 * 分析カラーをライトモードで安全に表示するためのコントラスト補正。
 * 色相を保ちながら輝度を下げ、白背景に対してWCAG AA水準(4.5:1)を近似する。
 * isDark=true（ダークモード）のときは色をそのまま返す。
 *
 * 典型的な問題: perfColor(0.5) ≈ #dddddd（neutral gray）は白背景で不可視。
 * 本関数で rgb(109,109,109) 程度に補正し、コントラスト比 4.6:1 を確保する。
 */
export function lightSafe(color: string, isDark: boolean): string {
  if (isDark) return color
  // rgb(r,g,b) または #rrggbb をパース
  let r: number, g: number, b: number
  const rgbM = color.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/)
  const hexM = color.match(/^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i)
  if (rgbM) {
    r = +rgbM[1]; g = +rgbM[2]; b = +rgbM[3]
  } else if (hexM) {
    r = parseInt(hexM[1], 16); g = parseInt(hexM[2], 16); b = parseInt(hexM[3], 16)
  } else {
    return color
  }
  // WCAG 相対輝度（sRGB → 線形）
  const lin = (c: number) => {
    const v = c / 255
    return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4)
  }
  const lum = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
  // lum<=0.18 なら白背景でコントラスト比≥4.5:1 → そのまま返す
  if (lum <= 0.18) return color
  // sRGB スケールダウン（色相維持・輝度削減）
  // target lum = 0.18 → scale = sqrt(0.18 / lum) で近似
  const scale = Math.sqrt(0.18 / lum)
  return `rgb(${Math.round(r * scale)},${Math.round(g * scale)},${Math.round(b * scale)})`
}
