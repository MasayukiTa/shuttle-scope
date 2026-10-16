/**
 * Phase B: ショット種別 → カテゴリ → 色のセマンティックマッピング。
 *
 * 階層分離 (hybrid_ui_implementation_plan_v2.md §7.1 参照):
 *   - 表示グループ (ShotTypePanel.buildGroups の出力) はコンテキスト依存で動的
 *   - 色カテゴリ (ここ) はショットタイプ単位で固定
 *   - ボタンは「所属表示グループに関わらず、ショットタイプから引いた色」で塗る
 *
 * 例: after_back_attack コンテキストで `defend` グループに block (シアン) /
 *     lob (黄) / drive (緑) が混在表示される — 想定通り、混在で OK。
 *
 * カラーブラインド対応: 各カテゴリに形状アイコン併記 (◆ ● ■ ★ ✕)。
 * コントラスト: 白文字に対し全カテゴリ WCAG AA (4.5:1) 以上。背景は 700 番台を使う
 * (600 番台は green 3.3 / cyan 3.7 / amber 3.2 で AA を割っていた)。
 * hover は明るくせず一段暗くする (明るくすると押下前に比率が落ちる)。
 */
import { ShotType } from '@/types'

export type ShotCategory = 'attack' | 'net' | 'mid' | 'serve' | 'other'

export interface CategoryStyle {
  /** Tailwind 背景色クラス */
  bg: string
  /** Tailwind 背景色 hover クラス */
  bgHover: string
  /** Tailwind 文字色クラス */
  text: string
  /** Tailwind ボーダー色クラス */
  border: string
  /** カラーブラインド対応形状アイコン */
  icon: string
  /** i18n キー (`shot_color_categories.{key}`) */
  labelKey: string
  /** selected 時の追加 ring クラス */
  ringSelected: string
}

export const CATEGORY_STYLES: Record<ShotCategory, CategoryStyle> = {
  // ATTACK 🟢 — green-700 (白文字 5.0:1)
  attack: {
    bg: 'bg-green-700',
    bgHover: 'hover:bg-green-800',
    text: 'text-white',
    border: 'border-green-800',
    icon: '◆',
    labelKey: 'shot_color_categories.attack',
    ringSelected: 'ring-2 ring-white ring-offset-2 ring-offset-gray-900',
  },
  // NET 🔵 — cyan-700 (白文字 5.4:1)
  net: {
    bg: 'bg-cyan-700',
    bgHover: 'hover:bg-cyan-800',
    text: 'text-white',
    border: 'border-cyan-800',
    icon: '●',
    labelKey: 'shot_color_categories.net',
    ringSelected: 'ring-2 ring-white ring-offset-2 ring-offset-gray-900',
  },
  // MID 🟠 — amber-700 (白文字 5.0:1)
  // 旧 yellow-500 + text-gray-900 はカラフルタイル群で「黒文字だけ浮く」見栄え不良
  // だったため白文字に統一。amber-600 は白文字 3.2:1 で AA 未満だったため 700 にした
  mid: {
    bg: 'bg-amber-700',
    bgHover: 'hover:bg-amber-800',
    text: 'text-white',
    border: 'border-amber-800',
    icon: '■',
    labelKey: 'shot_color_categories.mid',
    ringSelected: 'ring-2 ring-white ring-offset-2 ring-offset-gray-900',
  },
  // SERVE 🟣 — violet-700 (白文字 7.1:1。600 より彩度・明度を落として画面全体の紫の主張を弱める)
  serve: {
    bg: 'bg-violet-700',
    bgHover: 'hover:bg-violet-800',
    text: 'text-white',
    border: 'border-violet-800',
    icon: '★',
    labelKey: 'shot_color_categories.serve',
    ringSelected: 'ring-2 ring-white ring-offset-2 ring-offset-gray-900',
  },
  // OTHER ⚫ — slate-600
  other: {
    bg: 'bg-slate-600',
    bgHover: 'hover:bg-slate-700',
    text: 'text-white',
    border: 'border-slate-700',
    icon: '✕',
    labelKey: 'shot_color_categories.other',
    ringSelected: 'ring-2 ring-white ring-offset-2 ring-offset-gray-900',
  },
}

/**
 * ShotType → ShotCategory のマッピング。
 *
 * - ATTACK: 速い・沈むスマッシュ系 + 攻撃ドライブ + ネット押し込み
 * - NET:    ネット前 / 守備系の応急ショット
 * - MID:    クリア・ロブ・スライスの高弾道中立
 * - SERVE:  サーブ
 * - OTHER:  分類不能
 *
 * around_head は attribute (is_around_head) として保持しているが、
 * ショット種別として直接選択される場合は ATTACK に分類 (バック後方の攻撃手段なため)。
 * cant_reach も技術的に届かなかったケースなので OTHER。
 */
export const SHOT_TYPE_CATEGORY: Record<ShotType, ShotCategory> = {
  // ATTACK
  smash: 'attack',
  half_smash: 'attack',
  push_rush: 'attack',
  drive: 'attack',
  around_head: 'attack',

  // NET / 守備
  net_shot: 'net',
  cross_net: 'net',
  flick: 'net',
  block: 'net',
  drop: 'net',
  defensive: 'net',

  // MID
  clear: 'mid',
  lob: 'mid',
  slice: 'mid',

  // SERVE
  short_service: 'serve',
  long_service: 'serve',

  // OTHER
  other: 'other',
  cant_reach: 'other',
}

export function getCategoryForShot(shot: ShotType): ShotCategory {
  return SHOT_TYPE_CATEGORY[shot] ?? 'other'
}

export function getStyleForShot(shot: ShotType): CategoryStyle {
  return CATEGORY_STYLES[getCategoryForShot(shot)]
}
