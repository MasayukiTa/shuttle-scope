import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'

interface EvidenceMetaEntry {
  analysis_type: string
  tier: string
  evidence_level: string
  min_recommended_sample: number
  caution: string | null
  assumptions: string | null
  promotion_criteria: string | null
  /** 昇格レビューの手動判定 (promotion_ready / requires_review / insufficient_data / hold)。無ければ null */
  override_status?: string | null
}

/**
 * バックエンドの evidence メタデータをキャッシュして返すフック。
 * 全 research card で共有できるよう staleTime を長めに設定。
 *
 * 使い方:
 *   const { getMeta } = useAnalysisMeta()
 *   const meta = getMeta('epv_state')
 */
export function useAnalysisMeta() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['analysis-meta-evidence'],
    queryFn: () =>
      apiGet<{ success: boolean; data: EvidenceMetaEntry[] }>('/analysis/meta/evidence'),
    staleTime: 10 * 60 * 1000, // 10分キャッシュ
    gcTime: 30 * 60 * 1000,
  })

  const entries = data?.data ?? []
  const metaMap = Object.fromEntries(entries.map((e) => [e.analysis_type, e]))

  function getMeta(analysisType: string): EvidenceMetaEntry | undefined {
    return metaMap[analysisType]
  }

  /**
   * 昇格レビューで hold にされた分析か。true のカードは数値を出さない。
   * メタ取得に失敗したときは override 状態が不明なため、fail-open せず
   * 安全側（hold 扱い）に倒す。障害時に未審査の数値を出さないための防御。
   */
  function isOnHold(analysisType: string): boolean {
    if (isError) return true
    return metaMap[analysisType]?.override_status === 'hold'
  }

  return { getMeta, isOnHold, isLoading, isError, allMeta: entries }
}
