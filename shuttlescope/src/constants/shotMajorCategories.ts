/**
 * 大分類（簡易入力モード）のフロント側定義。
 *
 * このファイルは backend/analysis/shot_taxonomy.py の大分類定義
 * (MAJOR_SHOTS / MAJOR_REPRESENTATIVE / MAJOR_OF_CANONICAL) のミラーです。
 * 両者がずれると、簡易モードで選んだ大分類がサーバで別の小分類に落ち、
 * 画面と解析が食い違う。テスト (shotMajorCategories.test.ts) でバックの
 * 定義と一致することを検査しています。
 *
 * 背景: 顧客要望の打合せ (2026-11-05) で、研究者・アナリストから
 * 「同じスマッシュでもそこまで細かく分類できない」という要望が出た。
 * 18 canonical 小分類は現場での素早い入力には細かすぎる場面があるため、
 * 9 大分類の粒度で入力できる簡易モードを用意する。
 *
 * 保存は従来どおり 18 分類の canonical 小分類で行います。大分類は「入力の束ね」
 * にすぎず、選ぶと代表となる小分類 (REPRESENTATIVE) に写像して送ります。
 */
import { ShotType } from '@/types'

/** 大分類コード（9種）。backend MAJOR_SHOTS と同順・同内容。 */
export const MAJOR_SHOTS = [
  'serve',
  'net',
  'drop',
  'clear',
  'smash',
  'drive',
  'lob',
  'defensive',
  'other',
] as const

export type MajorShot = (typeof MAJOR_SHOTS)[number]

/** 大分類 → 代表 canonical 小分類（簡易モードで選んだときに保存する shot_type）。 */
export const MAJOR_REPRESENTATIVE: Record<MajorShot, ShotType> = {
  serve: 'short_service',
  net: 'net_shot',
  drop: 'drop',
  clear: 'clear',
  smash: 'smash',
  drive: 'drive',
  lob: 'lob',
  defensive: 'defensive',
  other: 'other',
}

/** canonical 小分類 → 大分類（18→9 の逆写像）。全 18 分類を覆う。 */
export const MAJOR_OF_CANONICAL: Record<ShotType, MajorShot> = {
  short_service: 'serve',
  long_service: 'serve',
  net_shot: 'net',
  cross_net: 'net',
  push_rush: 'net',
  flick: 'net',
  block: 'net',
  drop: 'drop',
  clear: 'clear',
  slice: 'clear',
  smash: 'smash',
  half_smash: 'smash',
  around_head: 'smash',
  drive: 'drive',
  lob: 'lob',
  defensive: 'defensive',
  cant_reach: 'other',
  other: 'other',
}

/** 大分類 → 日本語ラベル（i18n キーが無い場面のフォールバック表示用）。 */
export const MAJOR_SHOT_JA: Record<MajorShot, string> = {
  serve: 'サーブ',
  net: 'ネット前',
  drop: 'ドロップ',
  clear: 'クリア',
  smash: 'スマッシュ',
  drive: 'ドライブ',
  lob: 'ロブ',
  defensive: '守備',
  other: 'その他',
}

/** canonical 小分類を大分類へ畳む。未知は 'other'。 */
export function majorOf(shot: ShotType): MajorShot {
  return MAJOR_OF_CANONICAL[shot] ?? 'other'
}

/** 大分類の代表 canonical 小分類を返す。 */
export function representativeOf(major: MajorShot): ShotType {
  return MAJOR_REPRESENTATIVE[major]
}
