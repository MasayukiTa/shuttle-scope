/**
 * parseSlots — 会話駆動スコープのクライアント側プレビュー抽出。
 *
 * バックエンド (backend/analysis/chat/slot_extractors.py) のミラー。
 * period は既存の parsePeriod.ts を再利用、shot_type / zone を新規追加。
 *
 * 用途: composer 入力中に chip プレビューを即時表示する。最終確定は
 *       サーバ抽出 + クライアント送信値の merge で決まる (last-write-wins)。
 */
import { parsePeriod, ParsedPeriod } from './parsePeriod'

export type ShotTypeCode =
  | 'smash'
  | 'clear'
  | 'drop'
  | 'net'
  | 'drive'
  | 'push'
  | 'lob'
  | 'serve'

export type ZoneCode = 'FL' | 'FR' | 'BL' | 'BR' | 'FRONT' | 'BACK' | 'SIDE'

export interface ParsedShotType {
  code: ShotTypeCode
  label: string
  matchedText: string
}

export interface ParsedZone {
  code: ZoneCode
  label: string
  matchedText: string
}

const SHOT_SYNONYMS: Array<{ code: ShotTypeCode; words: string[] }> = [
  { code: 'smash', words: ['スマッシュ', 'smash'] },
  { code: 'clear', words: ['クリア', 'clear'] },
  { code: 'drop', words: ['ドロップ', 'drop'] },
  { code: 'net', words: ['ネット', 'ヘアピン', 'net shot', 'net'] },
  { code: 'drive', words: ['ドライブ', 'drive'] },
  { code: 'push', words: ['プッシュ', 'push'] },
  { code: 'lob', words: ['ロブ', 'ロビング', 'lob'] },
  { code: 'serve', words: ['サーブ', 'serve'] },
]

const ZONE_SYNONYMS: Array<{ code: ZoneCode; words: string[]; label: string }> = [
  { code: 'FL', words: ['FL', 'フォア前', '前衛フォア'], label: 'フォア前' },
  { code: 'FR', words: ['FR', 'バック前', '前衛バック'], label: 'バック前' },
  { code: 'BL', words: ['BL', 'フォア奥', '後衛フォア'], label: 'フォア奥' },
  { code: 'BR', words: ['BR', 'バック奥', '後衛バック'], label: 'バック奥' },
  { code: 'FRONT', words: ['前衛', 'ネット前', '前方'], label: '前' },
  { code: 'BACK', words: ['後衛', 'コート奥', '後方'], label: '奥' },
  { code: 'SIDE', words: ['サイドライン際', 'サイドライン', 'サイド際'], label: 'サイド' },
]

const NEG_TPL_JA = ['{}以外', '{}じゃない', '{}ではない', '{}を除く']
const NEG_TPL_EN = ['not {}', 'except {}', 'no {}']

function hasNegationAround(text: string, word: string): boolean {
  const low = text.toLowerCase()
  const wlow = word.toLowerCase()
  for (const tpl of NEG_TPL_JA) {
    if (text.includes(tpl.replace('{}', word))) return true
  }
  for (const tpl of NEG_TPL_EN) {
    if (low.includes(tpl.replace('{}', wlow))) return true
  }
  return false
}

export function parseShotType(input: string): ParsedShotType | null {
  if (!input) return null
  const low = input.toLowerCase()
  for (const { code, words } of SHOT_SYNONYMS) {
    for (const w of words) {
      const wlow = w.toLowerCase()
      const hit =
        input.includes(w) ||
        new RegExp(`\\b${wlow.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\$&')}\\b`).test(low)
      if (hit && !hasNegationAround(input, w)) {
        return { code, label: w, matchedText: w }
      }
    }
  }
  return null
}

export function parseZone(input: string): ParsedZone | null {
  if (!input) return null
  for (const { code, words, label } of ZONE_SYNONYMS) {
    for (const w of words) {
      if (input.includes(w) && !hasNegationAround(input, w)) {
        return { code, label, matchedText: w }
      }
    }
  }
  return null
}

export interface ParsedSlots {
  period: ParsedPeriod
  shotType: ParsedShotType | null
  zone: ParsedZone | null
}

export function parseAllSlots(
  input: string,
  now: Date = new Date(),
  lang: 'ja' | 'en' = 'ja',
): ParsedSlots {
  return {
    period: parsePeriod(input, now, lang),
    shotType: parseShotType(input),
    zone: parseZone(input),
  }
}
