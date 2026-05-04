/**
 * Phase C speed: flipMode (auto / semi-auto / manual) のユニットテスト
 *
 * カバー範囲:
 *  - 'auto' は常に flip
 *  - 'manual' は flip しない
 *  - 'semi-auto' は flip するが 500ms 以内の次ショット tap で revert
 *  - 500ms 経過後の次ショット tap は revert しない
 */
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { useAnnotationStore } from '../annotationStore'

describe('annotationStore flipMode', () => {
  beforeEach(() => {
    // store を初期化
    useAnnotationStore.getState().init(1, 1, 1, 1, 0, 0, 'player_a')
    useAnnotationStore.setState({ isRallyActive: true, currentStrokeNum: 1 })
  })

  it('auto mode flips currentPlayer on selectLandZone', () => {
    useAnnotationStore.getState().setFlipMode('auto')
    useAnnotationStore.getState().inputShotType('smash', 0)
    expect(useAnnotationStore.getState().currentPlayer).toBe('player_a')
    useAnnotationStore.getState().selectLandZone(5)
    expect(useAnnotationStore.getState().currentPlayer).toBe('player_b')
  })

  it('manual mode keeps currentPlayer on selectLandZone', () => {
    useAnnotationStore.getState().setFlipMode('manual')
    useAnnotationStore.getState().inputShotType('smash', 0)
    useAnnotationStore.getState().selectLandZone(5)
    expect(useAnnotationStore.getState().currentPlayer).toBe('player_a')
  })

  it('semi-auto flips on selectLandZone but reverts on next inputShotType within 500ms', () => {
    vi.useFakeTimers()
    try {
      useAnnotationStore.getState().setFlipMode('semi-auto')
      useAnnotationStore.getState().inputShotType('smash', 0)
      useAnnotationStore.getState().selectLandZone(5)
      // flipped → player_b
      expect(useAnnotationStore.getState().currentPlayer).toBe('player_b')

      // 200ms 後に次ショット → revert される
      vi.advanceTimersByTime(200)
      useAnnotationStore.getState().inputShotType('drive', 0)
      expect(useAnnotationStore.getState().currentPlayer).toBe('player_a')
    } finally {
      vi.useRealTimers()
    }
  })

  it('semi-auto does NOT revert if next inputShotType is after 500ms', () => {
    vi.useFakeTimers()
    try {
      useAnnotationStore.getState().setFlipMode('semi-auto')
      useAnnotationStore.getState().inputShotType('smash', 0)
      useAnnotationStore.getState().selectLandZone(5)
      expect(useAnnotationStore.getState().currentPlayer).toBe('player_b')

      vi.advanceTimersByTime(800)
      useAnnotationStore.getState().inputShotType('drive', 0)
      // No revert, stays player_b
      expect(useAnnotationStore.getState().currentPlayer).toBe('player_b')
    } finally {
      vi.useRealTimers()
    }
  })

  it('setFlipMode persists choice via localStorage', () => {
    useAnnotationStore.getState().setFlipMode('manual')
    expect(window.localStorage.getItem('ss_flip_mode')).toBe('manual')
    useAnnotationStore.getState().setFlipMode('auto')
    expect(window.localStorage.getItem('ss_flip_mode')).toBe('auto')
  })
})
