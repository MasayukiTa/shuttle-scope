// 研究タブ bundle 配信コンテキスト
// DashboardResearchPage で 1 回だけ bundle を取得し、各カードへスライスとして配布する。
// backend 側 bundle endpoint が未実装（useResearchBundle が undefined を返す）でも
// 各カードは provided=false として個別 fetch にフォールバックできる。
import { createContext, useContext, ReactNode } from 'react'
import type { ResearchBundleKey, ResearchBundleResponse } from '@/hooks/useResearchBundle'

interface ResearchBundleCtxValue {
  data: ResearchBundleResponse | undefined
  isLoading: boolean
}

// 既定値は「bundle 非提供」モード — Provider 外で使っても各カードは従来通り動く
const Ctx = createContext<ResearchBundleCtxValue | null>(null)

interface ProviderProps {
  value: ResearchBundleCtxValue
  children: ReactNode
}

export function ResearchBundleProvider({ value, children }: ProviderProps) {
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

/**
 * 指定カードのスライスを返す。
 *
 * 戻り値の意味:
 * - `provided=false`: bundle 提供なし（Provider 外 / bundle 取得失敗 / slice が null）
 *   → カードは個別 fetch にフォールバックすべき
 * - `provided=true, loading=true`: bundle 取得中
 * - `provided=true, slice=値`: bundle 取得済み、このデータを使用可
 */
export function useResearchBundleSlice<T = unknown>(
  key: ResearchBundleKey,
): { slice: T | null; loading: boolean; provided: boolean } {
  const ctx = useContext(Ctx)
  if (!ctx) return { slice: null, loading: false, provided: false }
  if (ctx.isLoading) return { slice: null, loading: true, provided: true }
  // bundle 取得失敗（undefined）→ provided=false で個別 fetch へ
  if (!ctx.data) return { slice: null, loading: false, provided: false }
  const raw = ctx.data.data?.[key] ?? null
  const slice = raw as T | null
  return { slice, loading: false, provided: slice !== null }
}
