/**
 * ダブルスのサーバ引き継ぎ。
 *
 * 旧実装は confirmRally のたびに打者を勝者チームの主選手へ戻していたので、
 * サーブ側が連続得点しても（同じ選手が続けてサーブするルール）、
 * partner がサーブしたラリーの次が主選手のサーブとして記録された。
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { useAnnotationStore } from '../annotationStore'
import type { StrokeInput } from '@/types'

const stroke = (player: string): StrokeInput => ({
  stroke_num: 1,
  player,
  shot_type: 'short_service',
  land_zone: 'BC',
  timestamp_sec: 1,
} as StrokeInput)

describe('annotationStore のダブルスのサーバ', () => {
  beforeEach(() => {
    useAnnotationStore.getState().init(1, 1, 1, 1, 0, 0, 'player_a')
    useAnnotationStore.setState({ isDoubles: true })
  })

  it('サーブ側が得点したら同じ選手が続けてサーブする', () => {
    useAnnotationStore.setState({ currentStrokes: [stroke('partner_a')] })
    useAnnotationStore.getState().confirmRally('player_a', 'ace')
    const s = useAnnotationStore.getState()
    expect(s.currentPlayer).toBe('player_a')
    expect(s.currentHitter).toBe('partner_a')
  })

  it('サーブ権が移ったときは勝者チームの主選手に置く', () => {
    useAnnotationStore.setState({ currentStrokes: [stroke('partner_a')] })
    useAnnotationStore.getState().confirmRally('player_b', 'ace')
    const s = useAnnotationStore.getState()
    expect(s.currentPlayer).toBe('player_b')
    expect(s.currentHitter).toBe('player_b')
  })

  it('シングルスでは従来どおり勝者の側に揃える', () => {
    useAnnotationStore.setState({ isDoubles: false, currentStrokes: [stroke('player_a')] })
    useAnnotationStore.getState().confirmRally('player_a', 'ace')
    expect(useAnnotationStore.getState().currentHitter).toBe('player_a')
  })
})
