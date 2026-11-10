import { describe, it, expect } from 'vitest'
import ja from '../ja.json'
import en from '../en.json'

// Sendai University request #8: "打点" (contact height) names a HEIGHT, not a
// place, so it must not label where a shot was played from. PR #263 fixed the
// landing/hit-zone pad headings, but the detail-input row still read
// "打点位置:" and the analysis heatmap tab still read "打点" (observed on the
// muse device, 2026-11-10). This test pins the location labels to the
// canonical shot-location wording (ja: 打球位置 / en: Shot location) and keeps
// the HEIGHT labels (打点高さ / 打点の高さ / Contact height) unchanged.
type Dict = Record<string, unknown>

const jaEnrichment = (ja as Dict).enrichment as Dict
const enEnrichment = (en as Dict).enrichment as Dict
const jaHeat = (ja as Dict).court_heat_modal as Dict
const enHeat = (en as Dict).court_heat_modal as Dict
const jaShotmap = (ja as Dict).shotmap as Dict
const enShotmap = (en as Dict).shotmap as Dict

describe('request #8: hit-position labels name a location, not a height', () => {
  it('ja: the detail-input location row no longer reads 打点位置', () => {
    expect(jaEnrichment.contact_zone).toBe('打球位置')
    expect(jaEnrichment.contact_zone as string).not.toContain('打点')
  })

  it('ja: the analysis heatmap location labels read 打球位置, not 打点', () => {
    for (const k of ['tab_hit', 'legend_hit', 'header_hit', 'zone_mode_hit'] as const) {
      expect(jaHeat[k]).toBe('打球位置')
      expect(jaHeat[k] as string).not.toContain('打点')
    }
    expect(jaShotmap.hit_point).toBe('打球位置')
    expect(jaShotmap.hit_point as string).not.toContain('打点')
  })

  it('ja: the whole file no longer contains the string 打点位置', () => {
    const text = JSON.stringify(ja)
    expect(text).not.toContain('打点位置')
  })

  it('ja: HEIGHT labels still use 打点 (打点高さ / 打点の高さ are kept)', () => {
    expect(jaEnrichment.contact_height).toBe('打点高さ')
    const reviewUi = ((ja as Dict).annotator as Dict).ux as Dict
    expect(reviewUi.review_f_height).toBe('打点の高さ')
    const text = JSON.stringify(ja)
    expect(text).toContain('打点高さ')
    expect(text).toContain('打点の高さ')
  })

  it('en: location labels read "Shot location", not "Hit point"/"Contact zone"', () => {
    expect(enEnrichment.contact_zone).toBe('Shot location')
    for (const k of ['tab_hit', 'legend_hit', 'header_hit', 'zone_mode_hit'] as const) {
      expect(enHeat[k]).toBe('Shot location')
    }
    expect(enShotmap.hit_point).toBe('Shot location')
  })

  it('en: HEIGHT labels still read "Contact height"', () => {
    expect(enEnrichment.contact_height).toBe('Contact height')
  })

  it('ja: hit-zone UI labels (correct/apply/prompt/tutorial) read 打球位置, not 打点', () => {
    const ui = ((ja as Dict).annotator as Dict).ui as Dict
    expect(ui.sc_hit_zone).toBe('打球位置を修正')
    expect(ui.sc_hit_zone_doubles).toBe('打球位置を修正（ダブルス時）')
    expect(ui.cv_apply_hit_only).toBe('打球位置のみ')
    expect(ui.cv_apply_hit_only_title as string).toContain('打球位置ゾーン')
    expect(ui.cv_apply_hit_only_title as string).not.toContain('打点ゾーン')
    const prompt = (((ja as Dict).auto as Dict).Pass3ShotDetail as Dict).prompt_hit_zone as string
    expect(prompt).toContain('打球位置を選択')
    expect(prompt).not.toContain('打点')
    const hz = (((ja as Dict).tutorials as Dict).desktop_annotator as Dict).hitZone as Dict
    expect(hz.title).toBe('打球位置ゾーンを入力')
    expect(hz.body as string).toContain('打球位置がコートのどこか')
    expect(hz.body as string).not.toContain('打点')
  })

  it('en: hit-zone UI labels read "shot location", not "hit zone"/"hit point"', () => {
    const ui = ((en as Dict).annotator as Dict).ui as Dict
    expect(ui.sc_hit_zone).toBe('Correct shot location')
    expect(ui.sc_hit_zone_doubles).toBe('Correct shot location (doubles)')
    expect(ui.cv_apply_hit_only).toBe('Shot location only')
    expect(ui.cv_apply_hit_only_title as string).toContain('shot locations')
    const prompt = (((en as Dict).auto as Dict).Pass3ShotDetail as Dict).prompt_hit_zone as string
    expect(prompt).toContain('Select shot location')
    const hz = (((en as Dict).tutorials as Dict).desktop_annotator as Dict).hitZone as Dict
    expect(hz.title).toBe('Pick the shot location')
  })
})
