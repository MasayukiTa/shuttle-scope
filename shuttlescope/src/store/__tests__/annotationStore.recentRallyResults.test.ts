/**
 * #784 の回帰テスト。
 *
 * 解析モード (AnalysisModePanel) は直近ラリーの勝敗を `recentRallyResults` から
 * 計算するが、productionではこの配列を生成・配線する source が store に無く、
 * 呼び出し元 (AnnotatorPage) が prop を渡していなかったため常に空=dead display
 * だった。ここでは store 側のデータ source を固定する:
 *   - 初期状態は空
 *   - confirmRally で勝者が追記される
 *   - skipRallyState (見逃しラリー) でも追記される
 *   - init / clearMatch でリセットされる
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { useAnnotationStore } from '../annotationStore'

describe('annotationStore の直近ラリー勝敗 (#784)', () => {
  beforeEach(() => {
    useAnnotationStore.getState().init(1, 1, 1, 1, 0, 0, 'player_a')
  })

  it('初期状態は空配列', () => {
    expect(useAnnotationStore.getState().recentRallyResults).toEqual([])
  })

  it('confirmRally が勝者を順に追記する', () => {
    useAnnotationStore.getState().confirmRally('player_a', 'winner')
    useAnnotationStore.getState().confirmRally('player_b', 'winner')
    expect(useAnnotationStore.getState().recentRallyResults).toEqual([
      { winner: 'player_a' },
      { winner: 'player_b' },
    ])
  })

  it('skipRallyState (見逃しラリー) も追記する', () => {
    useAnnotationStore.getState().skipRallyState('player_b')
    expect(useAnnotationStore.getState().recentRallyResults).toEqual([
      { winner: 'player_b' },
    ])
  })

  it('init は履歴をリセットする', () => {
    useAnnotationStore.getState().confirmRally('player_a', 'winner')
    useAnnotationStore.getState().init(2, 2, 1, 1, 0, 0, 'player_a')
    expect(useAnnotationStore.getState().recentRallyResults).toEqual([])
  })

  it('clearMatch は履歴をリセットする', () => {
    useAnnotationStore.getState().confirmRally('player_a', 'winner')
    useAnnotationStore.getState().clearMatch()
    expect(useAnnotationStore.getState().recentRallyResults).toEqual([])
  })
})
