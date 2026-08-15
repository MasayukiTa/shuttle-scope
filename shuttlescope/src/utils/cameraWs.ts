/**
 * カメラ signaling WebSocket の URL 組み立て。
 *
 * camera review #2 fix:
 *   operator / device / viewer の 3 箇所が同じ組み立てを個別に持ち、いずれも
 *   token を `isHttps` のときしか付けていなかった。サーバ側 `_ws_require_auth`
 *   は全ロールに JWT を要求し、operator 役に至ってはループバック緩和の対象外
 *   なので、Electron (file: → ws://localhost) と LAN 直結 (ws://192.168.x.x)
 *   では 3 ロールとも 4401 / 4403 で閉じられていた。
 *
 *   平文 ws:// に JWT を載せない意図でこの条件が置かれていたと解釈できるため、
 *   条件を外すのではなく「ループバック宛なら載せる」に変える。ループバックは
 *   ネットワークに出ないので露出は増えず、Electron が復旧する。
 *   LAN 平文経路は依然 token を送らない = 繋がらないままであり、これは
 *   短命 WS チケットで別途解決する (JWT を平文 LAN に流す代替は採らない)。
 */

const TOKEN_KEY = 'shuttlescope_token'

const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '::1', '[::1]'])

export function cameraWsUrl(
  sessionCode: string,
  params: Record<string, string | number>,
): string {
  // Electron(file:)                  → ws://localhost:8765
  // LAN 直接(http:)                   → ws://192.168.x.x:8765
  // Cloudflare named tunnel(https:)   → wss://app.shuttle-scope.com
  //                                     (ポートなし、Cloudflare が自動 WS upgrade)
  const isElectron = window.location.protocol === 'file:'
  const isHttps = window.location.protocol === 'https:'
  const wsProto = isHttps ? 'wss' : 'ws'
  const hostname = window.location.hostname || 'localhost'
  const wsHost = isElectron
    ? 'localhost:8765'
    : isHttps
      ? window.location.host
      : `${hostname}:8765`

  // https ならネットワーク上も暗号化される。file:/loopback は端末内で完結する。
  const isLoopbackTarget = isElectron || LOOPBACK_HOSTS.has(hostname)
  const token = isHttps || isLoopbackTarget
    ? (sessionStorage.getItem(TOKEN_KEY) ?? '')
    : ''

  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    query.set(key, String(value))
  }
  if (token) query.set('token', token)

  return `${wsProto}://${wsHost}/ws/camera/${encodeURIComponent(sessionCode)}?${query.toString()}`
}
