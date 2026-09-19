/**
 * A-8: 一時保存からの復元で壊れていたもの。
 *
 * 復元は保存されたストローク配列を `setState` で積み直すだけなので、
 * ストロークを 1 本入れるたびに走る状態遷移は再現されない。
 * 具体的に落ちていたのは 2 つ:
 *
 *   - `rallyStartTimestamp` — 旧実装は `store.rallyStartTimestamp ?? 0` で
 *     復元していた。リロード直後のストアは null なので必ず 0 になり、
 *     そのラリーは「動画の 0 秒から始まった」として保存されていた。
 *   - `currentPlayer` — ストロークごとに交替するので、積み直しただけでは
 *     打数が奇数のとき必ず逆になる。次の 1 本が別人のものになる。
 *
 * どちらも画面には何も出ない。
 */
import { describe, it, expect, beforeEach } from 'vitest'

import { useAnnotationStore } from '../annotationStore'

const reset = () => useAnnotationStore.setState({
  isRallyActive: false,
  rallyStartTimestamp: null,
  currentStrokes: [],
  currentPlayer: 'player_a',
  currentHitter: 'player_a',
})

describe('復元時のラリー開始位置', () => {
  beforeEach(reset)

  it('開始位置が分からないときは null のまま通す', () => {
    useAnnotationStore.getState().startRally(null)
    expect(useAnnotationStore.getState().rallyStartTimestamp).toBeNull()
    expect(useAnnotationStore.getState().isRallyActive).toBe(true)
  })

  it('0 秒は «先頭» という実在の値なので、欠損の代わりに使わない', () => {
    useAnnotationStore.getState().startRally(0)
    expect(useAnnotationStore.getState().rallyStartTimestamp).toBe(0)
    // null と 0 が別物として残ること。ここが同じになると、
    // 欠損を「動画の先頭」として保存する旧挙動に戻る。
    reset()
    useAnnotationStore.getState().startRally(null)
    expect(useAnnotationStore.getState().rallyStartTimestamp).not.toBe(0)
  })

  it('通常の開始はそのまま保持する', () => {
    useAnnotationStore.getState().startRally(123.5)
    expect(useAnnotationStore.getState().rallyStartTimestamp).toBe(123.5)
  })
})

describe('復元時の打順', () => {
  beforeEach(reset)

  it('startRally は currentPlayer を触らない — 復元側が入れ直す必要がある', () => {
    useAnnotationStore.setState({ currentPlayer: 'player_b', currentHitter: 'player_b' })
    useAnnotationStore.getState().startRally(1.0)
    expect(useAnnotationStore.getState().currentPlayer).toBe('player_b')
  })

  it('保存値を戻せば打順が復元される', () => {
    useAnnotationStore.getState().startRally(1.0)
    // AnnotatorPage の復元が行うのと同じ書き戻し
    useAnnotationStore.setState({ currentPlayer: 'player_b', currentHitter: 'partner_b' })
    expect(useAnnotationStore.getState().currentPlayer).toBe('player_b')
    expect(useAnnotationStore.getState().currentHitter).toBe('partner_b')
  })
})
