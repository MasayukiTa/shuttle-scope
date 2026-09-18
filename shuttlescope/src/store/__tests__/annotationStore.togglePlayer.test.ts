/**
 * A-7 の回帰テスト。
 *
 * Tab は凡例に「プレイヤー切替」と書いてあるのに toggleHitterWithinTeam に
 * 繋がっており、シングルスでは `if (!s.isDoubles) return {}` で**何も起きな
 * かった**。preventDefault だけは効くので Tab のフォーカス移動も死んでおり、
 * シングルスで打者の取り違えを直す手段がキーボードに存在しなかった。
 *
 * ここで固定するのは store の 2 つの toggle の役割分担。
 * AnnotatorPage の onToggleHitter はこの分岐をそのまま使う。
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { useAnnotationStore } from '../annotationStore'

describe('annotationStore の打者切替', () => {
  beforeEach(() => {
    useAnnotationStore.getState().init(1, 1, 1, 1, 0, 0, 'player_a')
  })

  it('togglePlayer は側を入れ替え、ヒッターも主プレイヤーに揃える', () => {
    useAnnotationStore.getState().togglePlayer()
    expect(useAnnotationStore.getState().currentPlayer).toBe('player_b')
    expect(useAnnotationStore.getState().currentHitter).toBe('player_b')

    useAnnotationStore.getState().togglePlayer()
    expect(useAnnotationStore.getState().currentPlayer).toBe('player_a')
  })

  it('toggleHitterWithinTeam はシングルスでは何もしない', () => {
    useAnnotationStore.setState({ isDoubles: false })
    const before = useAnnotationStore.getState().currentHitter
    useAnnotationStore.getState().toggleHitterWithinTeam()
    expect(useAnnotationStore.getState().currentHitter).toBe(before)
  })

  it('toggleHitterWithinTeam はダブルスでチーム内を入れ替える (側は変えない)', () => {
    useAnnotationStore.setState({ isDoubles: true })
    useAnnotationStore.getState().toggleHitterWithinTeam()
    const s = useAnnotationStore.getState()
    expect(s.currentHitter).not.toBe('player_a')
    expect(s.currentPlayer).toBe('player_a')
  })

  it('シングルスで側を変える手段が存在する (A-7 の本体)', () => {
    useAnnotationStore.setState({ isDoubles: false })
    // Tab の実配線と同じ分岐
    const tab = () => {
      const s = useAnnotationStore.getState()
      if (s.isDoubles) s.toggleHitterWithinTeam()
      else s.togglePlayer()
    }
    tab()
    expect(useAnnotationStore.getState().currentPlayer).toBe('player_b')
  })
})
