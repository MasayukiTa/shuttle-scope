/**
 * Phase B: shotTypeColors マッピング単体テスト
 */
import { describe, it, expect } from 'vitest'
import {
  CATEGORY_STYLES,
  SHOT_TYPE_CATEGORY,
  getCategoryForShot,
  getStyleForShot,
} from '../shotTypeColors'
import { contrastRatio, hexToRgb } from '@/utils/contrast'

describe('shotTypeColors', () => {
  it('all 5 categories have a style entry', () => {
    expect(Object.keys(CATEGORY_STYLES).sort()).toEqual(
      ['attack', 'mid', 'net', 'other', 'serve'].sort(),
    )
  })

  it('every category style has required fields', () => {
    for (const cat of Object.values(CATEGORY_STYLES)) {
      expect(cat.bg).toMatch(/^bg-/)
      expect(cat.bgHover).toMatch(/^hover:bg-/)
      expect(cat.text).toMatch(/^text-/)
      expect(cat.icon.length).toBeGreaterThan(0)
      expect(cat.labelKey).toMatch(/^shot_color_categories\./)
    }
  })

  it('classifies smash family as attack', () => {
    expect(getCategoryForShot('smash')).toBe('attack')
    expect(getCategoryForShot('half_smash')).toBe('attack')
    expect(getCategoryForShot('drive')).toBe('attack')
    expect(getCategoryForShot('push_rush')).toBe('attack')
    expect(getCategoryForShot('around_head')).toBe('attack')
  })

  it('classifies net / defensive shots as net', () => {
    expect(getCategoryForShot('net_shot')).toBe('net')
    expect(getCategoryForShot('drop')).toBe('net')
    expect(getCategoryForShot('flick')).toBe('net')
    expect(getCategoryForShot('block')).toBe('net')
    expect(getCategoryForShot('cross_net')).toBe('net')
    expect(getCategoryForShot('defensive')).toBe('net')
  })

  it('classifies clear / lob / slice as mid', () => {
    expect(getCategoryForShot('clear')).toBe('mid')
    expect(getCategoryForShot('lob')).toBe('mid')
    expect(getCategoryForShot('slice')).toBe('mid')
  })

  it('classifies services as serve', () => {
    expect(getCategoryForShot('short_service')).toBe('serve')
    expect(getCategoryForShot('long_service')).toBe('serve')
  })

  it('classifies other / cant_reach as other', () => {
    expect(getCategoryForShot('other')).toBe('other')
    expect(getCategoryForShot('cant_reach')).toBe('other')
  })

  it('every ShotType in the mapping resolves to a known category', () => {
    for (const [shot, cat] of Object.entries(SHOT_TYPE_CATEGORY)) {
      expect(CATEGORY_STYLES[cat]).toBeDefined()
      // sanity: getStyleForShot returns same style
      const style = getStyleForShot(shot as Parameters<typeof getStyleForShot>[0])
      expect(style.bg).toBe(CATEGORY_STYLES[cat].bg)
    }
  })

  it('mid category uses white text on amber-700 (WCAG AA)', () => {
    // 旧 yellow-500 + text-gray-900 はカラフルタイル群で「黒文字だけ浮く」見栄え不良
    // のため白文字に統一。amber-600 (#d97706) は白文字 3.2:1 で AA 未満だったため 700 にした
    expect(CATEGORY_STYLES.mid.text).toBe('text-white')
    expect(CATEGORY_STYLES.mid.bg).toBe('bg-amber-700')
  })

  it('全カテゴリの背景は通常状態・hover とも白文字で WCAG AA (4.5:1) 以上', () => {
    // Tailwind の既定パレット値 (使用している 700/800 番台と slate-600)
    const hex: Record<string, string> = {
      'green-700': '#15803d', 'green-800': '#166534',
      'cyan-700': '#0e7490', 'cyan-800': '#155e75',
      'amber-700': '#b45309', 'amber-800': '#92400e',
      'violet-700': '#6d28d9', 'violet-800': '#5b21b6',
      'slate-600': '#475569', 'slate-700': '#334155',
    }
    const white = hexToRgb('#ffffff')
    for (const [cat, style] of Object.entries(CATEGORY_STYLES)) {
      for (const cls of [style.bg, style.bgHover.replace('hover:', '')]) {
        const key = cls.replace('bg-', '')
        expect(hex[key], `${cat}: ${cls} の色定義`).toBeDefined()
        expect(contrastRatio(white, hexToRgb(hex[key])), `${cat}: ${cls}`).toBeGreaterThanOrEqual(4.5)
      }
    }
  })

  it('全カテゴリーが白文字 (タイル群でテキスト色を統一する規約)', () => {
    // ユーザ要望: 「カラーのボタンの中が黒文字はありえない。fff にしないと読めない」
    for (const cat of Object.keys(CATEGORY_STYLES) as Array<keyof typeof CATEGORY_STYLES>) {
      expect(CATEGORY_STYLES[cat].text).toBe('text-white')
    }
  })
})
