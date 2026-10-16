/**
 * 管理画面 (監査ログ・セキュリティ監視) に出る内部コードを日本語ラベルにする。
 *
 * バックエンドは `admin_audit_logs_viewed` や `probe_attempt` のような内部コードを返す。
 * そのまま表示すると管理者にも意味が通らないため、表示の直前にここを通す。
 * 辞書は i18n (auth.audit_log.action_names / security_log.event_names / security_log.severity)。
 * 辞書に無い新しいコードは、黙って空にせず元のコードをそのまま返す。
 */

type TFn = (key: string) => string

function lookup(t: TFn, key: string, code: string): string {
  const v = t(key)
  return !v || v === key ? code : v
}

/** 監査ログの操作コード → ラベル */
export function auditActionLabel(t: TFn, code: string): string {
  return lookup(t, `auth.audit_log.action_names.${code}`, code)
}

/** セキュリティイベントの種別コード → ラベル */
export function securityEventLabel(t: TFn, code: string): string {
  return lookup(t, `security_log.event_names.${code}`, code)
}

/** 重大度コード (info / warn / critical) → ラベル */
export function severityLabel(t: TFn, code: string): string {
  return lookup(t, `security_log.severity.${code}`, code)
}
