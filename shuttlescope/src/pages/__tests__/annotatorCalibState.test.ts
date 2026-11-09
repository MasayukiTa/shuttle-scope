import { describe, it, expect } from 'vitest'
import { noVideoCalibState } from '../annotatorCalibState'

// F-T003-05: 映像なしモードでの「キャリブレーションを開く」導線の状態判定。
// 押しても何も起きず理由も出ないケースが無いことを固定する。
describe('noVideoCalibState (F-T003-05)', () => {
  it('ボタン未押下なら案内テキストのみ (hint)', () => {
    expect(
      noVideoCalibState({ courtGridVisible: false, matchId: '42', videoWindowOpen: false }),
    ).toBe('hint')
    // matchId 無し・別モニタ中でも、未押下なら hint のまま
    expect(
      noVideoCalibState({ courtGridVisible: false, matchId: undefined, videoWindowOpen: true }),
    ).toBe('hint')
  })

  it('押下 + 試合あり + 別モニタなし なら校正画面を開く (calib)', () => {
    expect(
      noVideoCalibState({ courtGridVisible: true, matchId: '42', videoWindowOpen: false }),
    ).toBe('calib')
  })

  it('押下 + 試合未保存 なら理由を出す (blocked_no_match)', () => {
    expect(
      noVideoCalibState({ courtGridVisible: true, matchId: undefined, videoWindowOpen: false }),
    ).toBe('blocked_no_match')
    // 空文字も未保存扱い
    expect(
      noVideoCalibState({ courtGridVisible: true, matchId: '', videoWindowOpen: false }),
    ).toBe('blocked_no_match')
  })

  it('押下 + 別モニタ再生中 なら理由を出す (blocked_external)', () => {
    expect(
      noVideoCalibState({ courtGridVisible: true, matchId: '42', videoWindowOpen: true }),
    ).toBe('blocked_external')
  })

  it('別モニタ再生中は試合未保存より優先して blocked_external', () => {
    // 校正キャンバスと別モニタ再生は競合するため、external を先に案内する
    expect(
      noVideoCalibState({ courtGridVisible: true, matchId: undefined, videoWindowOpen: true }),
    ).toBe('blocked_external')
  })

  it('押下中はいずれの入力でも hint を返さない (無反応を作らない)', () => {
    for (const matchId of [undefined, '', '7'] as const) {
      for (const videoWindowOpen of [false, true]) {
        const s = noVideoCalibState({ courtGridVisible: true, matchId, videoWindowOpen })
        expect(s).not.toBe('hint')
      }
    }
  })
})
