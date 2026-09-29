/**
 * カメラ signaling WS URL の組み立て。
 *
 * 背景: operator / device / viewer の 3 箇所が同じ組み立てを重複して持ち、
 * いずれも token を `isHttps` のときだけ付けていた。サーバは全ロールに JWT を
 * 要求し operator 役はループバック緩和の対象外なので、Electron (file:) と
 * LAN 直結 (http:) では 3 ロールとも接続できなかった。
 * ここでは「どの経路で token を載せるか」を固定する。
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

import { cameraWsUrl } from '../cameraWs'

const TOKEN = 'jwt-abc123'

/** window.location と sessionStorage を差し替える。 */
function setLocation(protocol: string, host: string): void {
  const [hostname, port] = host.split(':')
  vi.stubGlobal('window', {
    location: { protocol, host, hostname, port: port ?? '' },
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
  sessionStorage.clear()
})

describe('cameraWsUrl', () => {
  it('https では wss + ホストのポート無しで組み立て、token を載せる', () => {
    sessionStorage.setItem('shuttlescope_token', TOKEN)
    setLocation('https:', 'app.shuttle-scope.com')

    const url = new URL(cameraWsUrl('ABC123', { role: 'operator' }))

    expect(url.protocol).toBe('wss:')
    expect(url.host).toBe('app.shuttle-scope.com')
    expect(url.pathname).toBe('/ws/camera/ABC123')
    expect(url.searchParams.get('role')).toBe('operator')
    expect(url.searchParams.get('token')).toBe(TOKEN)
  })

  it('Electron (file:) でも token を載せる — 載せないと operator が 4403 で閉じられる', () => {
    sessionStorage.setItem('shuttlescope_token', TOKEN)
    setLocation('file:', '')

    const url = new URL(cameraWsUrl('ABC123', { role: 'operator' }))

    expect(url.protocol).toBe('ws:')
    expect(url.host).toBe('localhost:8765')
    expect(url.searchParams.get('token')).toBe(TOKEN)
  })

  it('localhost 宛の平文でも token を載せる（端末内で完結し露出しない）', () => {
    sessionStorage.setItem('shuttlescope_token', TOKEN)
    setLocation('http:', 'localhost:5173')

    const url = new URL(cameraWsUrl('ABC123', { participant_id: 42 }))

    expect(url.host).toBe('localhost:8765')
    expect(url.searchParams.get('participant_id')).toBe('42')
    expect(url.searchParams.get('token')).toBe(TOKEN)
  })

  // nosemgrep: javascript.lang.security.detect-insecure-websocket.detect-insecure-websocket
  it('LAN 平文 (ws スキーム) には token を載せない', () => {
    sessionStorage.setItem('shuttlescope_token', TOKEN)
    setLocation('http:', '192.168.1.20:5173')

    const url = new URL(cameraWsUrl('ABC123', { participant_id: 42 }))

    expect(url.host).toBe('192.168.1.20:8765')
    expect(url.searchParams.has('token')).toBe(false)
  })

  it('viewer は正式名 viewer_id を送る（旧 vid ではサーバが close(4000) する）', () => {
    setLocation('https:', 'app.shuttle-scope.com')

    const url = new URL(cameraWsUrl('ABC123', { role: 'viewer', viewer_id: 7 }))

    expect(url.searchParams.get('viewer_id')).toBe('7')
    expect(url.searchParams.has('vid')).toBe(false)
  })

  it('token が無ければ token パラメータ自体を付けない', () => {
    setLocation('https:', 'app.shuttle-scope.com')

    const url = new URL(cameraWsUrl('ABC123', { role: 'operator' }))

    expect(url.searchParams.has('token')).toBe(false)
  })

  it('入場券を使うときは JWT を URL に出さない', () => {
    // 入場券だけで認証が完結するのに JWT まで載せると、URL がログや Referer に
    // 残ったときの被害が入場券方式にした意味ごと消える。
    sessionStorage.setItem('shuttlescope_token', TOKEN)
    setLocation('https:', 'app.shuttle-scope.com')

    const url = new URL(cameraWsUrl('ABC123', { ticket: 'tkt-xyz' }))

    expect(url.searchParams.get('ticket')).toBe('tkt-xyz')
    expect(url.searchParams.has('token')).toBe(false)
  })
})
