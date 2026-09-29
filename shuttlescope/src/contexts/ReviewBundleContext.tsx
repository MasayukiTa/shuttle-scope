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
 *
 * R47 fix (= ResearchBundleContext と同じ問題の対応):
 *   旧実装は bundle ロード中に `provided=true, loading=true` を返し、
 *   各カードの個別 fetch を `enabled: !provided && !bundleLoading` で
 *   ブロックしていた。bundle endpoint が遅いと全カードが「読み込み中」
 *   のまま固まり、別タブ往復で初めて表示される最悪 UX になっていた。
 *   修正: bundle ロード中は provided=false を返し、個別 fetch を並列発火
 *   させる。bundle 完了時に slice があれば優先 (`bundled ?? indiv.data`)。
 */
export function useReviewBundleSlice<T = unknown>(
  key: ReviewBundleKey,
): { slice: T | null; loading: boolean; provided: boolean } {
  const ctx = useContext(Ctx)
  if (!ctx) return { slice: null, loading: false, provided: false }
  // bundle ロード中 / 失敗時はどちらも個別 fetch にフォールバック
  if (!ctx.data) return { slice: null, loading: false, provided: false }
  const slice = (ctx.data.data?.[key] ?? null) as T | null
  return { slice, loading: false, provided: slice !== null }
}
