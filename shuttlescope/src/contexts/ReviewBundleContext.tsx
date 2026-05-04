// 振り返りタブ bundle 配信コンテキスト
// DashboardReviewPage で 1 回だけ bundle を取得し、各カードへスライスとして配布する
import { createContext, useContext, ReactNode } from 'react'
import type { ReviewBundleKey, ReviewBundleResponse } from '@/hooks/useReviewBundle'

interface ReviewBundleCtxValue {
  data: ReviewBundleResponse | undefined
  isLoading: boolean
}

// 既定値は「bundle 非提供」モード — 各カードは従来の個別 useQuery にフォールバックする
const Ctx = createContext<ReviewBundleCtxValue | null>(null)

interface ProviderProps {
  value: ReviewBundleCtxValue
  children: ReactNode
}

export function ReviewBundleProvider({ value, children }: ProviderProps) {
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

/**
 * 指定カードのデータスライスを返す。
 * - bundle が未提供（Provider 外）→ undefined（フォールバックで個別取得してもらう合図）
 * - bundle がロード中 → { loading: true }
 * - bundle 取得済みでそのカードが null（個別失敗）→ undefined（同上）
 */
export function useReviewBundleSlice<T = unknown>(
  key: ReviewBundleKey,
): { slice: T | null; loading: boolean; provided: boolean } {
  const ctx = useContext(Ctx)
  if (!ctx) return { slice: null, loading: false, provided: false }
  if (ctx.isLoading) return { slice: null, loading: true, provided: true }
  const slice = (ctx.data?.data?.[key] ?? null) as T | null
  return { slice, loading: false, provided: slice !== null }
}
