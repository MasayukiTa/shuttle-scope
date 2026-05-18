/**
 * useQuery の「まだ data がない」状態を安全に判定するヘルパー。
 *
 * 背景:
 *   React Query v5 では、`enabled: false` のクエリは
 *     `isPending: true, isFetching: false, isLoading: false`
 *   を返す。`isLoading` だけを見て分岐すると "disabled 中" を "no data" と
 *   誤判定し、ユーザに「データ不足」を虚偽提示してしまう。
 *
 * 本ヘルパーは「まだ確定的にデータが無いとは言えない」状態を一括判定する。
 *
 * 真であれば「データを取得しています」を表示し、
 *   `<NoDataMessage loading=true ... />` を渡せばよい。
 */
export interface QueryLikeGate {
  isPending?: boolean
  isFetching?: boolean
  isLoading?: boolean
  isError?: boolean
  data?: unknown
}

/**
 * 「ロード中 / 初回未到達 / disabled 待ち」のいずれかなら true。
 * data がすでに到着していれば false。
 */
export function isQueryStillResolving(q: QueryLikeGate): boolean {
  // データが到着しているなら確実に "resolved"
  if (q.data !== undefined && q.data !== null) return false
  // 初回 pending (enabled 待ち含む) は true
  if (q.isPending) return true
  // refetch 中 (data が消えた状態は普通起こらないが念のため)
  if (q.isFetching) return true
  // 古い v4 互換: isLoading だけ来た場合
  if (q.isLoading) return true
  return false
}
