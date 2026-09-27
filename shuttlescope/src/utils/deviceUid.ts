/**
 * 端末固有 ID。
 *
 * サーバの join は `device_uid` を「同じ端末候補」の検索に使う。
 * ただし device_uid 単独では既存 participant（承認状態を含む）を再利用せず、
 * 前回 join の participant token を併せて証明できた場合だけ再接続扱いにする。
 *
 * 認証の材料ではない。あくまで「同じ端末候補か」の手掛かりとして使う。
 */
const DEVICE_UID_KEY = 'ss_device_uid'
let memoryFallbackUid = ''

function getSessionFallback(): string {
  try {
    const existing = sessionStorage.getItem(DEVICE_UID_KEY)
    if (existing) return existing
    const uid = crypto.randomUUID()
    sessionStorage.setItem(DEVICE_UID_KEY, uid)
    return uid
  } catch {
    if (!memoryFallbackUid) memoryFallbackUid = crypto.randomUUID()
    return memoryFallbackUid
  }
}

export function getDeviceUid(): string {
  try {
    const existing = localStorage.getItem(DEVICE_UID_KEY)
    if (existing) return existing
    const uid = crypto.randomUUID()
    localStorage.setItem(DEVICE_UID_KEY, uid)
    return uid
  } catch {
    // localStorage が拒否されても、同一タブ内では stable な UID を維持する。
    // sessionStorage も使えない環境だけ module-memory fallback に落とす。
    return getSessionFallback()
  }
}
