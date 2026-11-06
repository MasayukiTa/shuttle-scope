import { describe, it, expect } from 'vitest'
import ja from '@/i18n/ja.json'
import en from '@/i18n/en.json'

// Audit item 139: the conformal-prediction coverage headline must not claim
// that the (theoretical) guarantee "holds" from a single held-out result.
// The met/not-met label is softened to an empirical statement about the
// target being met on the held-out data, and the hint separates the
// empirical check from the assumption-dependent theoretical guarantee.
describe('ConformalCard coverage wording (audit 139)', () => {
  const jaCard = (ja as any).auto?.ConformalCard
  const enCard = (en as any).auto?.ConformalCard

  it('guarantee labels exist in both ja and en', () => {
    for (const card of [jaCard, enCard]) {
      expect(typeof card?.guarantee_met).toBe('string')
      expect(typeof card?.guarantee_not_met).toBe('string')
      expect(typeof card?.coverage_hint).toBe('string')
      expect(card.guarantee_met.length).toBeGreaterThan(0)
      expect(card.guarantee_not_met.length).toBeGreaterThan(0)
      expect(card.coverage_hint.length).toBeGreaterThan(0)
    }
  })

  it('ja label does not assert the guarantee itself is established', () => {
    // must not be the bare over-strong claim "保証成立"
    expect(jaCard.guarantee_met).not.toBe('保証成立')
    // empirical framing: references the held-out / target achievement
    expect(jaCard.guarantee_met).toContain('目標達成')
    expect(jaCard.guarantee_met).toContain('実測')
  })

  it('en label does not assert a bare "Guarantee met"', () => {
    expect(enCard.guarantee_met).not.toBe('Guarantee met')
    expect(enCard.guarantee_met.toLowerCase()).toContain('empirical')
    expect(enCard.guarantee_met.toLowerCase()).toContain('target')
  })

  it('ja hint separates the empirical check from the theoretical guarantee', () => {
    const h = jaCard.coverage_hint
    expect(h).toContain('経験的')
    // theoretical guarantee is framed as assumption-dependent, not simply "成立"
    expect(h).toContain('前提')
    expect(h).not.toContain('分布フリー保証がホールドアウトデータ上で成立')
  })

  it('en hint separates the empirical check from the theoretical guarantee', () => {
    const h = enCard.coverage_hint.toLowerCase()
    expect(h).toContain('empirical')
    expect(h).toContain('assumption')
    expect(h).not.toContain('the distribution-free guarantee holds on the held-out data')
  })
})
