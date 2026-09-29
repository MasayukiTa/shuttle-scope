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
 * - `provided=false`: bundle 提供なし、または bundle ロード中
 *   → カードは個別 fetch を即座に発火する (= UX ブロック回避)
 * - `provided=true, slice=値`: bundle 取得済み、このデータを使用可
 *   (bundled が返ってきたら個別 fetch 結果より優先される)
 *
 * R47 fix:
 *   旧実装は bundle ロード中に `provided=true, loading=true` を返し、
 *   各カードの個別 fetch を `enabled: !provided && !bundleLoading` で
 *   ブロックしていた。bundle endpoint は 10 個の重い ML を逐次実行する
 *   ため 10-30s かかり、その間全カードが「読み込み中」のまま固まる。
 *   別タブに移動して戻ると bundle が裏で完了済 → 一気に表示される
 *   という最悪 UX になっていた。
 *   修正: bundle ロード中は provided=false を返し、個別 fetch を並列発火
 *   させる。bundle 完了時に slice があれば優先 (`bundled ?? indiv.data`)。
 */
export function useResearchBundleSlice<T = unknown>(
  key: ResearchBundleKey,
): { slice: T | null; loading: boolean; provided: boolean } {
  const ctx = useContext(Ctx)
  if (!ctx) return { slice: null, loading: false, provided: false }
  // bundle ロード中 / 失敗時はどちらも個別 fetch にフォールバックさせる
  if (!ctx.data) return { slice: null, loading: false, provided: false }
  const raw = ctx.data.data?.[key] ?? null
  const slice = raw as T | null
  return { slice, loading: false, provided: slice !== null }
}
