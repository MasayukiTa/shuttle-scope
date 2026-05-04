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
 * WCAG AAA: コントラスト比 7:1 以上 (黄色 mid のみ暗文字で対応)。
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
  // ATTACK 🟢 — green-600
  attack: {
    bg: 'bg-green-600',
    bgHover: 'hover:bg-green-500',
    text: 'text-white',
    border: 'border-green-700',
    icon: '◆',
    labelKey: 'shot_color_categories.attack',
    ringSelected: 'ring-2 ring-white ring-offset-2 ring-offset-gray-900',
  },
  // NET 🔵 — cyan-600
  net: {
    bg: 'bg-cyan-600',
    bgHover: 'hover:bg-cyan-500',
    text: 'text-white',
    border: 'border-cyan-700',
    icon: '●',
    labelKey: 'shot_color_categories.net',
    ringSelected: 'ring-2 ring-white ring-offset-2 ring-offset-gray-900',
  },
  // MID 🟡 — yellow-500 (黄色背景は暗文字でコントラスト確保)
  mid: {
    bg: 'bg-yellow-500',
    bgHover: 'hover:bg-yellow-400',
    text: 'text-gray-900',
    border: 'border-yellow-600',
    icon: '■',
    labelKey: 'shot_color_categories.mid',
    ringSelected: 'ring-2 ring-white ring-offset-2 ring-offset-gray-900',
  },
  // SERVE 🟣 — violet-600
  serve: {
    bg: 'bg-violet-600',
    bgHover: 'hover:bg-violet-500',
    text: 'text-white',
    border: 'border-violet-700',
    icon: '★',
    labelKey: 'shot_color_categories.serve',
    ringSelected: 'ring-2 ring-white ring-offset-2 ring-offset-gray-900',
  },
  // OTHER ⚫ — slate-600
  other: {
    bg: 'bg-slate-600',
    bgHover: 'hover:bg-slate-500',
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
