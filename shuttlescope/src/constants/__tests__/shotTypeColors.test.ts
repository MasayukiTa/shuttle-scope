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
      const style = getStyleForShot(shot as any)
      expect(style.bg).toBe(CATEGORY_STYLES[cat].bg)
    }
  })

  it('mid category uses dark text for contrast on yellow bg (WCAG AAA)', () => {
    expect(CATEGORY_STYLES.mid.text).toBe('text-gray-900')
  })
})
