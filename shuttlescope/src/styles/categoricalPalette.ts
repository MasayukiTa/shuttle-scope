/**
 * Categorical 配色パレット (Design Language v1.2 §6 準拠)。
 *
 * 用途:
 *   - **複数系列チャート** (折れ線、散布、棒) で各系列を識別するための色のみ。
 *   - 連続値 (ヒートマップ、密度) には使わない → coolwarm を使う。
 *   - 装飾目的では使わない (Design Language §12)。
 *
 * 設計方針:
 *   - 12 色で限界とし、それ以上必要なら **shape エンコード** (●▲■◆★) と
 *     組み合わせて系列数を倍化。
 *   - **mode 別 lightness 調整**:
 *       Light mode (白背景): saturation 65〜80%、lightness 30〜45% (暗めで
 *         白上で見える)。黄色を含めない。
 *       Dark mode (#1e293b 背景): saturation 55〜70%、lightness 65〜78%
 *         (明るめで暗背景で見える)。黒・紺を含めない。
 *   - 色相間隔 25°+ を確保し色弱 (deutera / prota / trita) で識別可。
 *   - **identity 一貫性**: 同じ系列は mode 切替後も同じ識別子 (`Cool`,
 *     `Warm` …) を維持。lightness だけが変わる。
 *
 * 使い方:
 *   ```tsx
 *   import { catColor, CAT_ORDER } from '@/styles/categoricalPalette'
 *   const isLight = useIsLightMode()
 *   <Line dataKey="f1" stroke={catColor('Cool', isLight)} />
 *   // または系列 index から自動割当:
 *   series.forEach((s, i) =>
 *     <Line stroke={catColor(CAT_ORDER[i % CAT_ORDER.length], isLight)} />
 *   )
 *   ```
 */

export type CatKey =
  | 'Cool'
  | 'Warm'
  | 'Green'
  | 'Magenta'
  | 'Amber'
  | 'Slate'
  | 'Teal'
  | 'Plum'
  | 'Rust'
  | 'Olive'
  | 'Indigo'
  | 'Brown'

export const CAT_PALETTE: Record<CatKey, { light: string; dark: string }> = {
  Cool:    { light: '#0E62B0', dark: '#7CB7F2' },  // 青 210°
  Warm:    { light: '#C6451E', dark: '#FF9270' },  // 朱 14°
  Green:   { light: '#1B8861', dark: '#5FD8A8' },  // 青緑 152°
  Magenta: { light: '#A63E7D', dark: '#E89BC5' },  // 桃紫 320°
  Amber:   { light: '#B86A07', dark: '#F5B569' },  // 橙 33°
  Slate:   { light: '#4B5563', dark: '#94A3B8' },  // 青灰 220°
  Teal:    { light: '#0F766E', dark: '#5EEAD4' },  // 深青緑 175°
  Plum:    { light: '#6B21A8', dark: '#C4B5FD' },  // 紫 270°
  Rust:    { light: '#9F1239', dark: '#FB7185' },  // 深紅 343°
  Olive:   { light: '#4D7C0F', dark: '#84CC16' },  // 黄緑 80°
  Indigo:  { light: '#3730A3', dark: '#A5B4FC' },  // 青紫 240°
  Brown:   { light: '#78350F', dark: '#D8C29A' },  // 茶/タン 25°
}

/**
 * 系列 index → CatKey の固定マッピング。
 * 重要: index が同じなら mode 切替後も同じ意味色になるよう、本配列は
 * 順序を変えない (= "F1 は常に Cool 青" 等のユーザ記憶を壊さない)。
 */
export const CAT_ORDER: readonly CatKey[] = [
  'Cool',
  'Warm',
  'Green',
  'Magenta',
  'Amber',
  'Slate',
  'Teal',
  'Plum',
  'Rust',
  'Olive',
  'Indigo',
  'Brown',
] as const

/** mode に応じた hex を返す。 */
export function catColor(key: CatKey, isLight: boolean): string {
  return isLight ? CAT_PALETTE[key].light : CAT_PALETTE[key].dark
}

/** 系列 index → 色 (mode 連動)。12 を超える index は wrap してから shape で
 * 区別する想定。13 番目以降は呼び出し側で `<Scatter shape="triangle">`
 * 等を併用する。 */
export function catColorByIndex(index: number, isLight: boolean): string {
  const key = CAT_ORDER[index % CAT_ORDER.length]
  return catColor(key, isLight)
}

/** 散布図用 recharts shape rotation。color × shape で識別性倍増 (≤60 系列)。 */
export const CAT_SHAPES = ['circle', 'square', 'triangle', 'diamond', 'star'] as const
export type CatShape = (typeof CAT_SHAPES)[number]

/** 系列 index → shape (12 色を一巡したら shape を変える)。 */
export function catShapeByIndex(index: number): CatShape {
  const cycle = Math.floor(index / CAT_ORDER.length)
  return CAT_SHAPES[cycle % CAT_SHAPES.length]
}
