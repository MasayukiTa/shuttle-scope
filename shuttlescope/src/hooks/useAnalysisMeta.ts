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
  const { data, isLoading } = useQuery({
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

  return { getMeta, isLoading, allMeta: entries }
}
