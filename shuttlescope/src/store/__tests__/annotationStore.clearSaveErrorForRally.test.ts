/**
 * fix/save-failed-clear の回帰テスト。
 *
 * 記録画面上部の赤い「保存失敗 N 件」は、同じラリーが後で保存成功しても
 * addSaveError のまま残り、clearSaveErrors (全消し) でしか消せなかった。
 * clearSaveErrorForRally で、成功したラリーの失敗記録だけを消し、
 * 件数を減らす。×ボタンの clearSaveErrors (全消し) も残す。
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { useAnnotationStore } from '../annotationStore'

describe('annotationStore の保存失敗の消去', () => {
  beforeEach(() => {
    useAnnotationStore.getState().init(1, 1, 1, 1, 0, 0, 'player_a')
  })

  it('失敗を 1 件記録し、同じラリーを成功で保存すると失敗件数が 0 に戻る', () => {
    // (1) 失敗を 1 件記録する
    useAnnotationStore.getState().addSaveError({ rallyNum: 5, error: 'boom' })
    expect(useAnnotationStore.getState().saveErrors).toHaveLength(1)

    // (2) 同じラリーを成功で保存する (保存成功時に呼ぶ処理)
    useAnnotationStore.getState().clearSaveErrorForRally(5)

    // (3) 失敗件数が 0 に戻る
    expect(useAnnotationStore.getState().saveErrors).toHaveLength(0)
  })

  it('他のラリーの失敗は残す (該当 rallyNum だけ消す)', () => {
    useAnnotationStore.getState().addSaveError({ rallyNum: 5, error: 'boom5' })
    useAnnotationStore.getState().addSaveError({ rallyNum: 6, error: 'boom6' })
    expect(useAnnotationStore.getState().saveErrors).toHaveLength(2)

    useAnnotationStore.getState().clearSaveErrorForRally(5)

    const errs = useAnnotationStore.getState().saveErrors
    expect(errs).toHaveLength(1)
    expect(errs[0].rallyNum).toBe(6)
  })

  it('同じラリーの失敗が複数あっても全部消す', () => {
    useAnnotationStore.getState().addSaveError({ rallyNum: 5, error: 'a' })
    useAnnotationStore.getState().addSaveError({ rallyNum: 5, error: 'b' })
    expect(useAnnotationStore.getState().saveErrors).toHaveLength(2)

    useAnnotationStore.getState().clearSaveErrorForRally(5)
    expect(useAnnotationStore.getState().saveErrors).toHaveLength(0)
  })

  it('×ボタンの clearSaveErrors は引き続き全件消す', () => {
    useAnnotationStore.getState().addSaveError({ rallyNum: 5, error: 'a' })
    useAnnotationStore.getState().addSaveError({ rallyNum: 6, error: 'b' })
    useAnnotationStore.getState().clearSaveErrors()
    expect(useAnnotationStore.getState().saveErrors).toHaveLength(0)
  })
})
