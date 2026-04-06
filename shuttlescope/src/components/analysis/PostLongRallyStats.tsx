// 長ラリー後パフォーマンス比較コンポーネント（通常時 vs 長ラリー後）
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { AnalysisFilters, DEFAULT_FILTERS } from '@/types'

interface PostLongRallyStatsProps {
  playerId: number
  filters?: AnalysisFilters
}

interface StatSummary {
  win_rate: number
  avg_rally_length: number
  count: number
}

interface PostLongResponse {
  success: boolean
  data: {
    normal: StatSummary
    post_long: StatSummary
    diff_win_rate: number
  }
  meta: { sample_size: number; confidence: { level: string; stars: string; label: string } }
}

function ComparisonCard({
  label,
  stats,
  highlight,
}: {
  label: string
  stats: StatSummary
  highlight: 'blue' | 'amber'
}) {
  const borderColor = highlight === 'blue' ? 'border-blue-500' : 'border-amber-500'
  const textColor = highlight === 'blue' ? 'text-blue-400' : 'text-amber-400'
  return (
    <div className={`bg-gray-700/50 rounded-lg p-3 border-l-4 ${borderColor}`}>
      <p className={`text-xs font-semibold mb-2 ${textColor}`}>{label}</p>
      <div className="space-y-1.5">
        <div className="flex justify-between text-xs">
          <span className="text-gray-400">勝率</span>
          <span className="text-white font-semibold">{(stats.win_rate * 100).toFixed(1)}%</span>
        </div>
        <div className="flex justify-between text-xs">
          <span className="text-gray-400">平均ラリー長</span>
          <span className="text-white">{stats.avg_rally_length.toFixed(1)}</span>
        </div>
        <div className="flex justify-between text-xs">
          <span className="text-gray-400">ラリー数</span>
          <span className="text-gray-300">{stats.count}</span>
        </div>
      </div>
    </div>
  )
}

export function PostLongRallyStats({ playerId, filters = DEFAULT_FILTERS }: PostLongRallyStatsProps) {
  const { t } = useTranslation()

  const fp = {
    ...(filters.result !== 'all' ? { result: filters.result } : {}),
    ...(filters.tournamentLevel ? { tournament_level: filters.tournamentLevel } : {}),
    ...(filters.dateFrom ? { date_from: filters.dateFrom } : {}),
    ...(filters.dateTo ? { date_to: filters.dateTo } : {}),
  }
  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-post-long-rally', playerId, filters],
    queryFn: () =>
      apiGet<PostLongResponse>('/analysis/post_long_rally_stats', { player_id: playerId, ...fp }),
    enabled: !!playerId,
  })

  if (isLoading) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.loading')}</div>
  }

  const data = resp?.data
  const sampleSize = resp?.meta?.sample_size ?? 0

  if (!data || sampleSize === 0) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.no_data')}</div>
  }

  const diffPct = (data.diff_win_rate * 100).toFixed(1)
  const isPositive = data.diff_win_rate >= 0

  return (
    <div className="space-y-3">
      <ConfidenceBadge sampleSize={sampleSize} />

      <div className="grid grid-cols-2 gap-3">
        <ComparisonCard
          label={t('analysis.post_long_rally.normal')}
          stats={data.normal}
          highlight="blue"
        />
        <ComparisonCard
          label={t('analysis.post_long_rally.post_long')}
          stats={data.post_long}
          highlight="amber"
        />
      </div>

      {/* 差分表示 */}
      <div className="text-center text-sm">
        <span className="text-gray-400">長ラリー後の勝率差: </span>
        <span className={isPositive ? 'text-emerald-400 font-semibold' : 'text-red-400 font-semibold'}>
          {isPositive ? '+' : ''}{diffPct}%
        </span>
      </div>

      <p className="text-xs text-gray-500 text-center">
        ※ 10打以上のラリーを長ラリーとして判定
      </p>
    </div>
  )
}
