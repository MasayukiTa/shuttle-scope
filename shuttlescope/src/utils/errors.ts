// 例外値から表示用メッセージを取り出す共通ヘルパー
// catch (e: unknown) で受けた値に対して安全にアクセスするために使用する。

export function errorMessage(e: unknown, fallback = ''): string {
  if (e instanceof Error) return e.message
  if (typeof e === 'string') return e
  if (e && typeof e === 'object') {
    const obj = e as { message?: unknown; detail?: unknown }
    if (typeof obj.message === 'string') return obj.message
    if (typeof obj.detail === 'string') return obj.detail
  }
  return fallback || String(e)
}

export function errorStatus(e: unknown): number | undefined {
  if (e && typeof e === 'object') {
    const s = (e as { status?: unknown }).status
    if (typeof s === 'number') return s
  }
  return undefined
}

export function errorBody(e: unknown): string {
  if (e && typeof e === 'object') {
    const b = (e as { body?: unknown }).body
    if (typeof b === 'string') return b
  }
  return ''
}
