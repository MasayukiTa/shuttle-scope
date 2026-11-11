import { describe, it, expect } from 'vitest'
import ja from '../ja.json'
import en from '../en.json'

// customer request #8 (follow-up to PR #263): "打点" names a HEIGHT,
// not a place. PR #263 fixed the detail-input row and the analysis heatmap tab,
// and hitPositionLabels.test.ts pins those. This file pins the REMAINING
// location labels that still read "打点" / "hit point" / "hit zone" so they use
// the canonical shot-location wording (ja: 打球位置 / en: shot location), while
// keeping the HEIGHT labels (打点高さ / 打点の高さ / Contact height) untouched.
type Dict = Record<string, unknown>

const get = (root: Dict, path: string): unknown =>
  path.split('.').reduce<unknown>((o, k) => (o as Dict)?.[k], root)

describe('request #8 (extra): remaining hit-position labels name a location', () => {
  it('ja: court/zone/prompt location labels read 打球位置, not 打点', () => {
    const cases: Array<[string, string]> = [
      ['annotator.ui.cv_apply_result_hit', ' (打球位置{{n}})'],
      ['auto.EffectiveDistributionMap.own_court', '自コート（打球位置）　'],
      ['auto.CourtDiagram.k4', '自コート（打球位置）'],
      ['auto.ReceivedVulnerabilityMap.k1', '相手コート（打球位置）→ 自コート（着地）'],
      ['auto.Pass2ServeFinal.prompt_serve_hit', 'サーブの打球位置を選択'],
      ['auto.Pass2ServeFinal.prompt_final_hit', '決まった一打の打球位置を選択'],
    ]
    for (const [path, expected] of cases) {
      expect(get(ja as Dict, path)).toBe(expected)
      expect(get(ja as Dict, path) as string).not.toContain('打点')
    }
  })

  it('ja: CV-apply zone labels read 打球位置ゾーン, not 打点ゾーン', () => {
    for (const path of ['auto.AnnotatorPage.k16', 'auto.AnnotatorPage.k19']) {
      expect(get(ja as Dict, path) as string).toContain('打球位置ゾーン')
      expect(get(ja as Dict, path) as string).not.toContain('打点ゾーン')
    }
  })

  it('ja: heatmap note/missingness text reads 打球位置, not 打点', () => {
    for (const path of ['court_heat_modal.missingness_hit', 'court_heat_modal.composite_note']) {
      expect(get(ja as Dict, path) as string).not.toContain('打点')
    }
  })

  it('ja: the whole file no longer contains 打点位置; HEIGHT labels still contain 打点高さ', () => {
    const text = JSON.stringify(ja)
    expect(text).not.toContain('打点位置')
    expect(text).toContain('打点高さ')
    expect(text).toContain('打点の高さ')
  })

  it('en: matching location labels read shot location, not hit point/hit zone', () => {
    expect(get(en as Dict, 'auto.EffectiveDistributionMap.own_court')).toBe('Own court (shot location) ')
    expect(get(en as Dict, 'auto.CourtDiagram.k4')).toBe('Home court (shot location)')
    expect(get(en as Dict, 'auto.ReceivedVulnerabilityMap.k1')).toBe('Opponent court (shot location) → Home court (landing)')
    expect(get(en as Dict, 'auto.Pass2ServeFinal.prompt_serve_hit')).toBe('Select the serve shot location')
    expect(get(en as Dict, 'auto.Pass2ServeFinal.prompt_final_hit')).toBe('Select the shot location of the deciding shot')
    expect(get(en as Dict, 'annotator.ui.cv_apply_result_hit')).toBe(' (shot location {{n}})')
    expect(get(en as Dict, 'court_heat_modal.missingness_hit') as string).not.toContain('hit point')
    expect(get(en as Dict, 'court_heat_modal.missingness_hit') as string).not.toContain('hit-point')
  })
})
