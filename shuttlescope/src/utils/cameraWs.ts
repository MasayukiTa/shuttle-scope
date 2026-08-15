/**
 * カメラ signaling WebSocket の URL 組み立て。
 *
 * camera review #2 fix:
 *   operator / device / viewer の 3 箇所が同じ組み立てを個別に持ち、いずれも
 *   token を `isHttps` のときしか付けていなかった。サーバ側 `_ws_require_auth`
 *   は全ロールに JWT を要求し、operator 役に至ってはループバック緩和の対象外
 *   なので、Electron (file: → ws スキームの localhost) と LAN 直結
 *   では 3 ロールとも 4401 / 4403 で閉じられていた。
 *
 *   平文 ws スキームに JWT を載せない意図でこの条件が置かれていたと解釈
 *   できるため、条件を外すのではなく「ループバック宛なら載せる」に変える。
 *   ループバックは
 *   ネットワークに出ないので露出は増えず、Electron が復旧する。
 *   LAN 平文経路は依然 token を送らない = 繋がらないままであり、これは
 *   短命 WS チケットで別途解決する (JWT を平文 LAN に流す代替は採らない)。
 */

import { apiPost } from '@/api/client'

const TOKEN_KEY = 'shuttlescope_token'

const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '::1', '[::1]'])

export function cameraWsUrl(
  sessionCode: string,
  params: Record<string, string | number>,
): string {
  // Electron(file:)                  → ws スキーム / localhost:8765
  // LAN 直接(http:)                   → ws スキーム / 192.168.x.x:8765
  // Cloudflare named tunnel(https:)   → wss スキーム / app.shuttle-scope.com
  //                                     (ポートなし、Cloudflare が自動 WS upgrade)
  const isElectron = window.location.protocol === 'file:'
  const isHttps = window.location.protocol === 'https:'
  // Electron (file:) と LAN 直結は平文 ws になる。ページ自体が平文で配信されて
  // いる以上ここだけ wss にはできない。資格情報は下で https / ループバック宛て
  // に限って載せ、平文 LAN には出さない。
  // nosemgrep: javascript.lang.security.detect-insecure-websocket.detect-insecure-websocket
  const wsProto = isHttps ? 'wss' : 'ws'
  const hostname = window.location.hostname || 'localhost'
  const wsHost = isElectron
    ? 'localhost:8765'
    : isHttps
      ? window.location.host
      : `${hostname}:8765`

  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    query.set(key, String(value))
  }

  // https ならネットワーク上も暗号化される。file:/loopback は端末内で完結する。
  const isLoopbackTarget = isElectron || LOOPBACK_HOSTS.has(hostname)
  // 入場券を使う場合は JWT を URL に出さない (入場券だけで認証が完結する)
  const token = !query.has('ticket') && (isHttps || isLoopbackTarget)
    ? (sessionStorage.getItem(TOKEN_KEY) ?? '')
    : ''
  if (token) query.set('token', token)

  // nosemgrep: javascript.lang.security.detect-insecure-websocket.detect-insecure-websocket
  return `${wsProto}://${wsHost}/ws/camera/${encodeURIComponent(sessionCode)}?${query.toString()}`
}

/**
 * 参加者 (スマホ / タブレット) の WS URL。
 *
 * これらの端末はアプリのアカウントを持たないので JWT が無い。join で得た
 * participant_token を本文で渡して 30 秒使い捨ての入場券に引き換え、
 * URL には入場券しか載せない (URL はログや Referer に残るため)。
 *
 * participant_token が無い場合はログイン済みユーザとして JWT 経路に戻す。
 */
export async function participantWsUrl(
  sessionCode: string,
  role: 'device' | 'viewer',
  participantId: number,
  participantToken: string,
): Promise<string> {
  if (!participantToken) {
    return cameraWsUrl(
      sessionCode,
      role === 'viewer'
        ? { role: 'viewer', viewer_id: participantId }
        : { participant_id: participantId },
    )
  }
  const res = await apiPost<{ success: boolean; data: { ticket: string } }>(
    `/sessions/${sessionCode}/ws-ticket`,
    { participant_id: participantId, participant_token: participantToken, role },
  )
  if (!res.success || !res.data?.ticket) throw new Error('ws ticket denied')
  return cameraWsUrl(sessionCode, { ticket: res.data.ticket })
}
