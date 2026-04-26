/**
 * バックエンドが返す ISO 8601 文字列を Date に変換するヘルパー。
 *
 * バックエンドは `datetime.utcnow()` で naive UTC を保存しており、
 * 大半のエンドポイントは `+ "Z"` 付き ISO で返す（main.py の ENCODERS_BY_TYPE 経由）。
 * ただし FastAPI `response_model=` 経由の一部エンドポイントは pydantic v2 の
 * 標準シリアライザを通り `Z` なし naive ISO で返ることがある。
 *
 * このヘルパーは:
 *   - すでに TZ 情報があるもの（"Z" / "+09:00" / "-05:00" 等）→ そのまま Date()
 *   - TZ 情報がないもの → 末尾に "Z" を付けて UTC として解釈
 *
 * いずれの場合も Date 自身は内部で UTC を保持し、`toLocaleString()` 等で
 * 自動的に local timezone (JST) に変換される。
 */
const TZ_RE = /(?:Z|[+-]\d{2}:?\d{2})$/

export function parseUTC(value: string | null | undefined): Date | null {
  if (!value) return null
  const trimmed = value.trim()
  if (!trimmed) return null
  // ms 付き ISO で TZ なしのものに "Z" を補う
  const withTz = TZ_RE.test(trimmed) ? trimmed : trimmed + 'Z'
  const d = new Date(withTz)
  return isNaN(d.getTime()) ? null : d
}

/**
 * 日本標準時 (Asia/Tokyo) で表示用文字列を返す。
 * value が null/不正な場合は空文字。
 */
export function formatJST(value: string | null | undefined, opts?: Intl.DateTimeFormatOptions): string {
  const d = parseUTC(value)
  if (!d) return ''
  const options: Intl.DateTimeFormatOptions = opts ?? {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    timeZone: 'Asia/Tokyo',
  }
  return d.toLocaleString('ja-JP', options)
}
