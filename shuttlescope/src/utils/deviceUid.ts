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

export function getDeviceUid(): string {
  try {
    const existing = localStorage.getItem(DEVICE_UID_KEY)
    if (existing) return existing
    const uid = crypto.randomUUID()
    localStorage.setItem(DEVICE_UID_KEY, uid)
    return uid
  } catch {
    // プライベートブラウズ等で localStorage が使えない場合は毎回新規でよい
    return crypto.randomUUID()
  }
}
