// コントラスト計算と、失点ヒートマップのセル内文字色の AA 適合を固定するテスト
import { describe, it, expect } from 'vitest'
import { blend, contrastRatio, hexToRgb, relativeLuminance } from '../contrast'
import { LOSS, LOSS_HEAT_MAX_ALPHA } from '@/styles/colors'

describe('contrast', () => {
  it('黒と白は 21:1、同色は 1:1', () => {
    const black = hexToRgb('#000000')
    const white = hexToRgb('#ffffff')
    expect(contrastRatio(black, white)).toBeCloseTo(21, 5)
    expect(contrastRatio(white, white)).toBeCloseTo(1, 5)
    expect(relativeLuminance(white)).toBeCloseTo(1, 5)
  })
})

describe('失点ヒートマップのセル内文字', () => {
  // globals.css の --ss-t1 / カード背景 (ライト: 白、ダーク: surface 想定の暗色)
  const cases = [
    { name: 'light', text: '#1a2028', bg: '#ffffff' },
    { name: 'dark', text: '#e6e9ed', bg: '#1a1f26' },
  ]

  for (const c of cases) {
    it(`${c.name}: 濃度 0〜最大の全域で文字が 4.5:1 以上`, () => {
      const loss = hexToRgb(LOSS)
      const bg = hexToRgb(c.bg)
      const text = hexToRgb(c.text)
      for (let i = 0; i <= 20; i++) {
        const alpha = (i / 20) * LOSS_HEAT_MAX_ALPHA
        const cell = blend(loss, alpha, bg)
        expect(contrastRatio(text, cell), `alpha=${alpha.toFixed(3)}`).toBeGreaterThanOrEqual(4.5)
      }
    })
  }

  it('旧仕様 (最大 0.65) ではライトの最濃セルで 4.5:1 を割る (上限を下げた根拠)', () => {
    const cell = blend(hexToRgb(LOSS), 0.65, hexToRgb('#ffffff'))
    expect(contrastRatio(hexToRgb('#1a2028'), cell)).toBeLessThan(4.5)
  })

  it('旧仕様の文字色 (セルと同じ LOSS) は最濃セルで 3:1 未満', () => {
    const cell = blend(hexToRgb(LOSS), 0.65, hexToRgb('#ffffff'))
    expect(contrastRatio(hexToRgb(LOSS), cell)).toBeLessThan(3)
  })
})
