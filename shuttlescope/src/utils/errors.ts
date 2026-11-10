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

/**
 * 保存の失敗が「再送で解決しうる一過性のもの」か「送り直しても直らない恒久的なもの」かを判定する。
 *
 * 背景 (要望2: 保存し終わったはずが「保存失敗」と出る):
 *   記録入力の保存 (POST /strokes/batch) は、送信前に端末 (IndexedDB) へ退避し、
 *   安定した X-Idempotency-Key を付けて送る。サーバがリクエストを受理して DB に
 *   書き込んだ後、その応答が端末へ届く前にタイムアウト (既定 60 秒) やネットワーク断が
 *   起きると、呼び出し側は失敗として扱ってしまう。だが実際にはサーバ側は保存済みで、
 *   退避は残っており、useOfflineSync が同じ冪等キーで再送するため二重には入らず最終的に
 *   整合する。この状態を「保存失敗」と断定して赤く見せると、保存できているのに失敗と
 *   誤って伝えることになる。
 *
 * 判定:
 *   - 恒久的 (permanent): HTTP ステータスが 4xx (ただし 408 Request Timeout と
 *     429 Too Many Requests を除く)。冪等キーで送り直しても同じ結果になる本当の失敗。
 *   - 一過性 (transient): 上記以外すべて。ステータスを持たない失敗 (タイムアウト・
 *     ネットワーク断)、408 / 429、5xx。退避に残して再送すれば解決しうる。
 *
 * この境界は useOfflineSync の再送判定 (再試行で直るものだけ中断し、直らない 4xx は
 *  別扱い) と一致させてある。
 */
export function isTransientSaveError(e: unknown): boolean {
  const status = errorStatus(e)
  if (typeof status !== 'number') {
    // ステータスが無い = タイムアウト / ネットワーク断など。再送で解決しうる。
    return true
  }
  const isPermanentClientError =
    status >= 400 && status < 500 && status !== 408 && status !== 429
  return !isPermanentClientError
}
