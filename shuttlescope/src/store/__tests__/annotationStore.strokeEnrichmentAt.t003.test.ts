/**
 * F-T003-01 の回帰テスト。
 *
 * 詳細分析 (エンリッチメント) 入力は従来「直前の確定ストローク」にしか付けら
 * れず、過去のストロークを後から補完できなかった。F-T003-01 で store に
 * `updateStrokeEnrichmentAt(index, fields)` を追加し、AnnotatorPage の詳細分析
 * パネルの ◀/▶ セレクタがこの index 指定更新を呼ぶ。
 *
 * ここで固定するのは store 側のロジックのみ (UI から独立して安定):
 *   - updateStrokeEnrichmentAt が指定 index のストロークだけを更新する
 *   - 範囲外 index は無視され、配列を壊さない
 *   - updateLastStrokeEnrichment は «直前» へ委譲する (後方互換)
 *   - currentStrokes が空のとき updateLastStrokeEnrichment は no-op
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { useAnnotationStore } from '../annotationStore'
import type { StrokeInput } from '@/types'

// 必須フィールドのみ満たす最小ストローク。index 識別のため stroke_num を使う。
function stroke(n: number): StrokeInput {
  return {
    stroke_num: n,
    player: 'player_a',
    shot_type: 'clear',
    is_backhand: false,
    is_around_head: false,
  }
}

describe('annotationStore の index 指定エンリッチメント (F-T003-01)', () => {
  beforeEach(() => {
    useAnnotationStore.getState().init(1, 1, 1, 1, 0, 0, 'player_a')
    useAnnotationStore.setState({ currentStrokes: [stroke(1), stroke(2), stroke(3)] })
  })

  it('updateStrokeEnrichmentAt は指定 index のストロークだけを更新する', () => {
    useAnnotationStore.getState().updateStrokeEnrichmentAt(0, { returnQuality: 'attack' })
    const s = useAnnotationStore.getState().currentStrokes
    expect(s[0].return_quality).toBe('attack')
    expect(s[1].return_quality).toBeUndefined()
    expect(s[2].return_quality).toBeUndefined()
  })

  it('中間の index も更新でき、他は不変', () => {
    useAnnotationStore.getState().updateStrokeEnrichmentAt(1, { contactHeight: 'overhead', intentTag: 'deep' })
    const s = useAnnotationStore.getState().currentStrokes
    expect(s[1].contact_height).toBe('overhead')
    expect(s[1].intent_tag).toBe('deep')
    expect(s[0].contact_height).toBeUndefined()
    expect(s[2].contact_height).toBeUndefined()
  })

  it('範囲外 index は無視され配列を壊さない', () => {
    const before = useAnnotationStore.getState().currentStrokes
    useAnnotationStore.getState().updateStrokeEnrichmentAt(-1, { returnQuality: 'attack' })
    useAnnotationStore.getState().updateStrokeEnrichmentAt(99, { returnQuality: 'attack' })
    const after = useAnnotationStore.getState().currentStrokes
    expect(after).toHaveLength(3)
    expect(after.some((x) => x.return_quality !== undefined)).toBe(false)
    // 参照ごと差し替わっていない (no-op なので set されない)
    expect(after).toBe(before)
  })

  it('updateLastStrokeEnrichment は «直前» (末尾) へ委譲する', () => {
    useAnnotationStore.getState().updateLastStrokeEnrichment({ returnQuality: 'defensive' })
    const s = useAnnotationStore.getState().currentStrokes
    expect(s[2].return_quality).toBe('defensive')
    expect(s[0].return_quality).toBeUndefined()
    expect(s[1].return_quality).toBeUndefined()
  })

  it('currentStrokes が空なら updateLastStrokeEnrichment は no-op', () => {
    useAnnotationStore.setState({ currentStrokes: [] })
    expect(() => useAnnotationStore.getState().updateLastStrokeEnrichment({ returnQuality: 'attack' })).not.toThrow()
    expect(useAnnotationStore.getState().currentStrokes).toEqual([])
  })

  it('同一ストロークに複数フィールドを段階的に付けられる', () => {
    const api = useAnnotationStore.getState()
    api.updateStrokeEnrichmentAt(2, { returnQuality: 'neutral' })
    api.updateStrokeEnrichmentAt(2, { contactZone: 'front' })
    api.updateStrokeEnrichmentAt(2, { movementBurden: 'high' })
    const s = useAnnotationStore.getState().currentStrokes[2]
    expect(s.return_quality).toBe('neutral')
    expect(s.contact_zone).toBe('front')
    expect(s.movement_burden).toBe('high')
  })
})
