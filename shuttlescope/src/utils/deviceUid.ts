/**
 * 端末固有 ID。
 *
 * サーバの join は `device_uid` が一致する参加者を「同じ端末の再接続」として
 * 再利用するが、どのクライアントもこれを送っていなかったため、リロードや
 * 再参加のたびに参加者行が増え続けていた (ゴースト端末)。
 * 参加者スコープの資格情報を出すようになった今は、放置された行がそれぞれ
 * 有効なトークンを抱えることになるので、なおさら送る必要がある。
 *
 * 認証の材料ではない。あくまで「同じ端末か」の手掛かりとして使う。
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
