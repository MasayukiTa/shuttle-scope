/**
 * #667: カメラ起動失敗の案内を「権限」と「接続」で分ける。
 *
 * 旧実装は getUserMedia() から WebRTC offer / signaling 送信までを 1 つの
 * try/catch で囲み、どの段で失敗しても「カメラへのアクセスを許可してください」と
 * 出していた。既に権限を許可していても、SDP 生成や signaling 送信の失敗まで
 * 権限問題として案内され、権限を見直しても直らない誤誘導になっていた。
 *
 * ここでは「分離した案内文が辞書とコードの双方に揃っていること」と「旧来の
 * 単一固定文言が残っていないこと」をソース走査で固定する。startCamera の全画面
 * レンダリングは参加フロー・WebRTC・getUserMedia のモックを要し重いため、i18n
 * キーの存在検証は staticKeys.test.ts に任せ、本テストは #667 の構造不変条件に絞る。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { resolve } from 'path'
import ja from '@/i18n/ja.json'
import en from '@/i18n/en.json'

type Dict = Record<string, unknown>

function camSender(dict: unknown): Dict {
  const cs = (dict as Dict).camera_sender
  expect(cs && typeof cs === 'object').toBe(true)
  return cs as Dict
}

const KEYS = [
  'camera_error_insecure',
  'camera_error_permission',
  'camera_error_notfound',
  'camera_error_inuse',
  'camera_error_generic',
  'connect_error',
]

describe('#667 camera start error separation', () => {
  it('権限/未検出/使用中/汎用/接続の案内キーが ja・en 両方にあり非空である', () => {
    const jcs = camSender(ja)
    const ecs = camSender(en)
    for (const k of KEYS) {
      expect(typeof jcs[k]).toBe('string')
      expect((jcs[k] as string).length).toBeGreaterThan(0)
      expect(typeof ecs[k]).toBe('string')
      expect((ecs[k] as string).length).toBeGreaterThan(0)
    }
  })

  it('権限の案内と接続の案内は別の文言である（同一 catch に戻していない）', () => {
    const jcs = camSender(ja)
    expect(jcs.camera_error_permission).not.toBe(jcs.connect_error)
  })

  const SRC = resolve(__dirname, '..', 'CameraSenderPage.tsx')
  const src = readFileSync(SRC, 'utf-8')

  it('startCamera が getUserMedia の DOMException 種別で案内を分けている', () => {
    // getUserMedia の失敗は端末カメラ側の問題として種別分岐する
    expect(src).toContain("camera_sender.camera_error_permission")
    expect(src).toContain("camera_sender.camera_error_notfound")
    expect(src).toContain("camera_sender.camera_error_inuse")
    expect(src).toMatch(/NotAllowedError/)
    expect(src).toMatch(/NotFoundError/)
    expect(src).toMatch(/NotReadableError/)
  })

  it('WebRTC/signaling 失敗は接続エラーとして別案内にする', () => {
    expect(src).toContain("camera_sender.connect_error")
  })

  it('旧来の単一固定文言「カメラへのアクセスを許可してください」が TSX から消えている', () => {
    // ハードコード日本語を i18n キーへ移したことの回帰ガード
    expect(src).not.toContain('カメラの起動に失敗しました。カメラへのアクセスを許可してください。')
    expect(src).not.toContain('カメラにアクセスできません。HTTPSまたはlocalhost')
  })
})
