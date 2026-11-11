/**
 * デバイス管理パネルの操作ボタン文言（アクティブカメラ行）。
 *
 * active_camera の行には2つの操作ボタンがある:
 *   - 「映像の開始を指示」 … onRequestCamera（旧「再リクエスト」/ハードコード「カメラ再リクエスト」を統一）
 *   - 「待機に戻す」       … onDeactivate（既存キー lan_session.action_deactivate）
 *
 * 以前は isStaleCamera の分岐で stale 時のみ i18n キー、通常時はハードコード
 * 日本語 'カメラ再リクエスト' が出ていた。文言ゆれと未翻訳(en)を解消するため
 * handoff.request_video_start に一本化した。
 *
 * このテストは翻訳リソースが両ロケールで揃っており、UI が参照するキーが
 * 期待文言になっていることを実ファイルで保証する（描画側は t(key) をそのまま出す）。
 */
import { describe, it, expect } from 'vitest'
import ja from '../../../i18n/ja.json'
import en from '../../../i18n/en.json'

type Dict = Record<string, Record<string, string>>

describe('DeviceManagerPanel handoff button labels', () => {
  it('ja: アクティブカメラ行の2ボタン文言が正しい', () => {
    expect((ja as Dict).handoff.request_video_start).toBe('映像の開始を指示')
    expect((ja as Dict).lan_session.action_deactivate).toBe('待機に戻す')
  })

  it('en: 同じキーが翻訳されている（未翻訳・日本語混入なし）', () => {
    expect((en as Dict).handoff.request_video_start).toBe('Start video')
    expect((en as Dict).lan_session.action_deactivate).toBe('Back to idle')
  })

  it('request_video_start は両ロケールに存在する', () => {
    expect((ja as Dict).handoff).toHaveProperty('request_video_start')
    expect((en as Dict).handoff).toHaveProperty('request_video_start')
  })
})
