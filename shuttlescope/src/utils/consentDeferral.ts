/**
 * 任意同意の「後で回答する」を一定期間覚えておくための小さなヘルパ。
 *
 * 任意同意は 1 件も記録されない限りサーバ側で「未回答」のままなので、「後で」を
 * 押しても毎回の再読み込みで同意画面が出直していた。端末ローカルに期限を保存し、
 * 期限内は再表示しない。サーバ側の同意状態は一切変更しない (= 未同意のまま)。
 * storage が使えない環境 (プライベートモード等) では何も覚えない (= 従来動作)。
 */
export const OPTIONAL_CONSENT_DEFER_DAYS = 7

const KEY_PREFIX = 'shuttlescope_optional_consent_deferred_until:'

function keyFor(userId: number | null | undefined): string {
  return `${KEY_PREFIX}${userId ?? 0}`
}

/** 「後で」を記録する。期限は now + days 日。 */
export function deferOptionalConsent(
  userId: number | null | undefined,
  now: number = Date.now(),
  days: number = OPTIONAL_CONSENT_DEFER_DAYS,
): void {
  try {
    window.localStorage.setItem(keyFor(userId), String(now + days * 86_400_000))
  } catch {
    /* storage 不可なら記憶しない */
  }
}

/** 期限内に「後で」が押されていれば true。 */
export function isOptionalConsentDeferred(
  userId: number | null | undefined,
  now: number = Date.now(),
): boolean {
  try {
    const raw = window.localStorage.getItem(keyFor(userId))
    if (!raw) return false
    const until = Number(raw)
    return Number.isFinite(until) && until > now
  } catch {
    return false
  }
}

/** 回答済みになったら記憶を消す。 */
export function clearOptionalConsentDeferral(userId: number | null | undefined): void {
  try {
    window.localStorage.removeItem(keyFor(userId))
  } catch {
    /* ignore */
  }
}
