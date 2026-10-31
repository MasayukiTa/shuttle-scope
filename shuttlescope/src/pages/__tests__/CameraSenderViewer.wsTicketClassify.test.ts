/**
 * #665: Camera/Viewer は ws-ticket (入場券) 取得失敗の理由を握りつぶし、
 * 401/403・参加トークン欠落・セッション消滅でも最大 25〜50 秒「再接続中」と
 * 待たせた末に汎用エラーへ変換していた。本来必要な「セッションに参加し直す」が
 * 利用者へ届かない。
 *
 * connectWs の catch で participantWsUrl の失敗を分類するよう修正した:
 *   - 401/403・participant_token 欠落 → error 状態 + 再参加案内 (rejoin_required)
 *   - 404/410                        → error 状態 + セッション終了案内 (session_gone)
 *   - 5xx/timeout/ネットワーク断のみ   → 有限回の自動再接続 (scheduleReconnect)
 *
 * 参加フロー・WebRTC・WebSocket のモックを要する全画面レンダリングは重いため、
 * #667 の既存テストと同様に、本テストは「分類文言が辞書とコードの双方に揃い、
 * catch が一律 scheduleReconnect へ戻していないこと」をソース走査で固定する。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { resolve } from 'path'
import ja from '@/i18n/ja.json'
import en from '@/i18n/en.json'

type Dict = Record<string, unknown>

function pick(dict: unknown, ...path: string[]): Dict {
  let cur: unknown = dict
  for (const key of path) {
    expect(cur && typeof cur === 'object').toBe(true)
    cur = (cur as Dict)[key]
  }
  expect(cur && typeof cur === 'object').toBe(true)
  return cur as Dict
}

describe('#665 ws-ticket failure classification', () => {
  it('camera_sender の再参加/セッション終了案内が ja・en 両方にあり非空である', () => {
    for (const dict of [ja, en]) {
      const cs = pick(dict, 'camera_sender')
      for (const k of ['rejoin_required', 'session_gone']) {
        expect(typeof cs[k]).toBe('string')
        expect((cs[k] as string).length).toBeGreaterThan(0)
      }
    }
  })

  it('auto.ViewerPage の再参加/セッション終了案内が ja・en 両方にあり非空である', () => {
    for (const dict of [ja, en]) {
      const vp = pick(dict, 'auto', 'ViewerPage')
      for (const k of ['rejoin_required', 'session_gone']) {
        expect(typeof vp[k]).toBe('string')
        expect((vp[k] as string).length).toBeGreaterThan(0)
      }
    }
  })

  const camSrc = readFileSync(resolve(__dirname, '..', 'CameraSenderPage.tsx'), 'utf-8')
  const viewerSrc = readFileSync(resolve(__dirname, '..', 'ViewerPage.tsx'), 'utf-8')

  for (const [label, src, nsKeyPrefix] of [
    ['CameraSenderPage', camSrc, 'camera_sender'],
    ['ViewerPage', viewerSrc, 'auto.ViewerPage'],
  ] as const) {
    describe(label, () => {
      it('errorStatus で入場券失敗を分類している', () => {
        expect(src).toContain('errorStatus')
        expect(src).toMatch(/401/)
        expect(src).toMatch(/403/)
        expect(src).toMatch(/404/)
        expect(src).toMatch(/410/)
      })

      it('auth/token 欠落・session 消滅を再参加/終了案内へ回している', () => {
        expect(src).toContain(`${nsKeyPrefix}.rejoin_required`)
        expect(src).toContain(`${nsKeyPrefix}.session_gone`)
      })

      it('catch が一律 scheduleReconnect へ戻していない (分岐の else にだけ残す)', () => {
        // participant_token 欠落も再接続対象にしていないこと
        expect(src).toContain('!savedTokenRef.current')
        // connectWs の catch 直後に無条件 scheduleReconnect を置いていないこと
        expect(src).not.toMatch(/\}\s*catch\s*\{\s*scheduleReconnect\(code, pid\)\s*return\s*\}/)
      })
    })
  }
})
