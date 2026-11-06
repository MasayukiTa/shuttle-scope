/**
 * #664 の回帰テスト。
 *
 * `/live/:matchId` の得点確定はワンタップ即保存で、確定後に直前得点を取り消す
 * 導線が無かった。store に `undoLastConfirmedRally(snapshot)` を追加し、確定の
 * 「前」に capture した snapshot (スコア・ラリー番号・サーバ) を使って状態を
 * 確定前へ戻せるようにした。ここでは store 側の巻き戻しを固定する:
 *   - スコア・ラリー番号・サーバが snapshot の値へ戻る
 *   - recentRallyResults の末尾 (この確定で足した 1 件) だけ取り除かれる
 *   - 入力途中状態 (currentStrokes / pendingStroke / inputStep) が idle へクリアされる
 *   - 1 回の確定につき 1 回だけ戻る (複数ラリーを一括では戻さない)
 *
 * server 側の DELETE /rallies/{id} は LiveInputPage 側の責務で、ここでは検証しない。
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { useAnnotationStore, type ConfirmedRallySnapshot } from '../annotationStore'

describe('annotationStore の直前得点取り消し (#664)', () => {
  beforeEach(() => {
    useAnnotationStore.getState().init(1, 1, 1, 1, 0, 0, 'player_a')
  })

  it('確定前に capture した snapshot でスコア・ラリー番号・サーバが戻る', () => {
    const store = useAnnotationStore.getState()
    // 確定前の値 (player_a が 0-0 でサーブ)
    const snapshot: ConfirmedRallySnapshot = {
      scoreA: store.scoreA,
      scoreB: store.scoreB,
      rallyNum: store.currentRallyNum,
      server: store.currentPlayer,
    }
    // player_b が得点 → スコア 0-1、ラリー 2、次サーバー player_b
    store.confirmRally('player_b', 'winner')
    expect(useAnnotationStore.getState().scoreB).toBe(1)
    expect(useAnnotationStore.getState().currentRallyNum).toBe(2)
    expect(useAnnotationStore.getState().currentPlayer).toBe('player_b')

    // 取り消し → 確定前へ戻る
    useAnnotationStore.getState().undoLastConfirmedRally(snapshot)
    const s = useAnnotationStore.getState()
    expect(s.scoreA).toBe(0)
    expect(s.scoreB).toBe(0)
    expect(s.currentRallyNum).toBe(1)
    expect(s.currentPlayer).toBe('player_a')
    expect(s.currentHitter).toBe('player_a')
  })

  it('recentRallyResults の末尾 1 件だけ取り除く', () => {
    const store = useAnnotationStore.getState()
    store.confirmRally('player_a', 'winner')
    const snapshot: ConfirmedRallySnapshot = {
      scoreA: useAnnotationStore.getState().scoreA,
      scoreB: useAnnotationStore.getState().scoreB,
      rallyNum: useAnnotationStore.getState().currentRallyNum,
      server: useAnnotationStore.getState().currentPlayer,
    }
    store.confirmRally('player_b', 'winner')
    expect(useAnnotationStore.getState().recentRallyResults).toEqual([
      { winner: 'player_a' },
      { winner: 'player_b' },
    ])
    useAnnotationStore.getState().undoLastConfirmedRally(snapshot)
    // 2 件目 (player_b) だけ消え、1 件目 (player_a) は残る
    expect(useAnnotationStore.getState().recentRallyResults).toEqual([
      { winner: 'player_a' },
    ])
  })

  it('入力途中状態をクリアして idle に戻す', () => {
    const store = useAnnotationStore.getState()
    const snapshot: ConfirmedRallySnapshot = {
      scoreA: store.scoreA,
      scoreB: store.scoreB,
      rallyNum: store.currentRallyNum,
      server: store.currentPlayer,
    }
    store.confirmRally('player_a', 'winner')
    // 次ラリーの入力を少し進める (ラリー開始 → shot_type が pending に載り land_zone へ)
    useAnnotationStore.getState().inputShotType('clear', 1)
    expect(useAnnotationStore.getState().isRallyActive).toBe(true)
    expect(useAnnotationStore.getState().pendingStroke.shot_type).toBe('clear')
    expect(useAnnotationStore.getState().inputStep).toBe('land_zone')

    useAnnotationStore.getState().undoLastConfirmedRally(snapshot)
    const s = useAnnotationStore.getState()
    expect(s.currentStrokes).toEqual([])
    expect(s.inputStep).toBe('idle')
    expect(s.currentStrokeNum).toBe(1)
    expect(s.isRallyActive).toBe(false)
    expect(s.pendingStroke.shot_type).toBeUndefined()
  })

  it('recentRallyResults が空なら何も壊さない (slice ガード)', () => {
    const store = useAnnotationStore.getState()
    // init 直後は履歴空。存在しないラリーの snapshot で呼んでも例外なく空のまま。
    const snapshot: ConfirmedRallySnapshot = {
      scoreA: 5,
      scoreB: 3,
      rallyNum: 9,
      server: 'player_b',
    }
    store.undoLastConfirmedRally(snapshot)
    const s = useAnnotationStore.getState()
    expect(s.recentRallyResults).toEqual([])
    // snapshot の値はそのまま反映される (呼び出し側が正しい値を渡す契約)
    expect(s.scoreA).toBe(5)
    expect(s.scoreB).toBe(3)
    expect(s.currentRallyNum).toBe(9)
    expect(s.currentPlayer).toBe('player_b')
  })
})
