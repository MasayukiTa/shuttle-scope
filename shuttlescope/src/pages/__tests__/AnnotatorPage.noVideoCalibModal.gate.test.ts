/**
 * F-T004-02 回帰テスト: 映像なしの状態で「キャリブレーションを開く」を押したとき、
 * コート校正のフルスクリーンモーダルを出す条件 (shouldShowNoVideoCalibModal) を検証する。
 *
 * 背景 (監査 T004 項目13):
 *   #314 (5f13ee08) でモーダルは追加されたが、表示条件が videoSourceMode==='none'
 *   に限定されていた。videoSourceMode の既定は 'local' で、ユーザーが明示的に 'local'
 *   のままソースが無い場合や、video_url が isPlayableVideoUrl で弾かれて実ソースが空の
 *   場合、matchDay/モバイルでは左パネルが非表示 + モーダル条件が false となり、
 *   校正画面がどこにも描画されない (「押しても何も起きない」) 経路が残っていた。
 *
 *   本テストは「再生可能な映像が無い」とき (videoSourceMode==='none' だけでなく、
 *   'local' でソース空も含む) にモーダルが出ること、かつ再生可能な映像がある/
 *   別ウィンドウ再生中/webview 待機中では出ないことを固定する。
 */
import { describe, it, expect } from 'vitest'
import { shouldShowNoVideoCalibModal } from '../AnnotatorPage'

describe('F-T004-02 映像なしキャリブレーションのモーダル表示条件', () => {
  const base = {
    courtGridVisible: true,
    matchId: '42',
    videoWindowOpen: false,
    isMatchDayMode: true,
    isMobile: false,
    hasPlayableVideo: false,
    videoSourceMode: 'local' as const,
  }

  it('matchDay + videoSourceMode=local だが再生可能映像が無いときモーダルを出す (回帰)', () => {
    expect(shouldShowNoVideoCalibModal(base)).toBe(true)
  })

  it('videoSourceMode=none (明示的に映像なし) でもモーダルを出す', () => {
    expect(shouldShowNoVideoCalibModal({ ...base, videoSourceMode: 'none' })).toBe(true)
  })

  it('モバイル + 再生可能映像が無いときモーダルを出す', () => {
    expect(
      shouldShowNoVideoCalibModal({ ...base, isMatchDayMode: false, isMobile: true }),
    ).toBe(true)
  })

  it('再生可能な映像があるときはモーダルを出さない (左パネル/プレーヤーに任せる)', () => {
    expect(shouldShowNoVideoCalibModal({ ...base, hasPlayableVideo: true })).toBe(false)
  })

  it('webview (カメラ/WebRTC 待機) はモーダルを出さない', () => {
    expect(shouldShowNoVideoCalibModal({ ...base, videoSourceMode: 'webview' })).toBe(false)
  })

  it('別ウィンドウで再生中はモーダルを出さない', () => {
    expect(shouldShowNoVideoCalibModal({ ...base, videoWindowOpen: true })).toBe(false)
  })

  it('courtGridVisible が false ならモーダルを出さない', () => {
    expect(shouldShowNoVideoCalibModal({ ...base, courtGridVisible: false })).toBe(false)
  })

  it('matchId が無いときはモーダルを出さない', () => {
    expect(shouldShowNoVideoCalibModal({ ...base, matchId: null })).toBe(false)
  })

  it('PC 詳細モード (非matchDay・非モバイル) では左パネルに出るためモーダルは出さない', () => {
    expect(
      shouldShowNoVideoCalibModal({ ...base, isMatchDayMode: false, isMobile: false }),
    ).toBe(false)
  })

  // ─── 分岐順序を固定する境界回帰 (customer request #4-4 スマホ映像/映像なし校正) ───

  it('webview は再生可能映像が無くてもモーダルを出さない (webview 判定が優先)', () => {
    expect(
      shouldShowNoVideoCalibModal({
        ...base,
        videoSourceMode: 'webview',
        hasPlayableVideo: false,
      }),
    ).toBe(false)
  })

  it('モバイル + videoSourceMode=none (明示映像なし) でもモーダルを出す', () => {
    expect(
      shouldShowNoVideoCalibModal({
        ...base,
        isMatchDayMode: false,
        isMobile: true,
        videoSourceMode: 'none',
      }),
    ).toBe(true)
  })

  it('PC 詳細モードは videoSourceMode=none でもモーダルを出さない (左パネル分岐が先)', () => {
    expect(
      shouldShowNoVideoCalibModal({
        ...base,
        isMatchDayMode: false,
        isMobile: false,
        videoSourceMode: 'none',
      }),
    ).toBe(false)
  })

  it('モバイル + webview は再生可能映像が無くてもモーダルを出さない', () => {
    expect(
      shouldShowNoVideoCalibModal({
        ...base,
        isMatchDayMode: false,
        isMobile: true,
        videoSourceMode: 'webview',
        hasPlayableVideo: false,
      }),
    ).toBe(false)
  })
})
