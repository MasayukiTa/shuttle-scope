/** サーバが返す安定したエラーコード (レスポンスヘッダ X-Error-Code)。 */
export const ERROR_CODE_HEADER = 'X-Error-Code'

/** MFA 第 2 段で、mfa_token そのものが失効・無効になったことを示すコード。
 *  MFA_TOKEN_INVALID_OR_EXPIRED: /auth/mfa/login ハンドラが返す。
 *  TOKEN_INVALID_OR_EXPIRED: 認証ミドルウェアが Bearer を検証できなかったときに返す。 */
const MFA_TOKEN_GONE_CODES: ReadonlySet<string> = new Set([
  'MFA_TOKEN_INVALID_OR_EXPIRED',
  'TOKEN_INVALID_OR_EXPIRED',
])

/** MFA ログイン失敗のうち、初段 (ID / パスワード入力) へ戻すべきものか。
 *  表示文言の部分一致には依存しない。401 だけで戻すと認証コードの打ち間違いまで
 *  初段へ戻ってしまうため、HTTP status とエラーコードの両方を見る。 */
export function shouldRestartMfaLogin(status: number, errorCode: string | null | undefined): boolean {
  return status === 401 && !!errorCode && MFA_TOKEN_GONE_CODES.has(errorCode)
}
