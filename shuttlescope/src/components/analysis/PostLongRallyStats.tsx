// 長ラリー後パフォーマンス比較コンポーネント（通常時 vs 長ラリー後）
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { AnalysisFilters, DEFAULT_FILTERS } from '@/types'
import { WIN, LOSS, BAR, LINE, N_GRAY } from '@/styles/colors'
import { useIsLightMode } from '@/hooks/useIsLightMode'

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
  highlight: 'normal' | 'post_long'
}) {
  const { t } = useTranslation()

  // Design Language v1.2 §2.7.0: **左罫線縦バー (border-l-4) は禁止** (詐欺サイト感)。
  // 区別は **タイトル文字色** で行う。post_long のみ accent 色を付ける。
  // bg / border は theme 連動の N_GRAY。
  const isLight = useIsLightMode()
  const accentColor = highlight === 'normal' ? BAR : LINE
  const cardBg     = isLight ? '#ffffff' : N_GRAY[800]
  const cardBorder = isLight ? N_GRAY[200] : N_GRAY[700]
  const labelColor = isLight ? N_GRAY[600] : N_GRAY[400]
  const valueColor = isLight ? N_GRAY[900] : N_GRAY[50]
  return (
    <div
      className="rounded-lg p-3"
      style={{ backgroundColor: cardBg, border: `1px solid ${cardBorder}` }}
    >
      {/* タイトル: highlight === 'post_long' のみ accent 色、それ以外は中立 */}
      <p
        className="text-xs font-semibold mb-2"
        style={{ color: highlight === 'post_long' ? accentColor : (isLight ? N_GRAY[700] : N_GRAY[200]) }}
      >
        {label}
      </p>
      <div className="space-y-1.5">
        <div className="flex justify-between text-xs">
          <span style={{ color: labelColor }}>{t('auto.PostLongRallyStats.k1')}</span>
          <span className="font-semibold tabular-nums" style={{ color: valueColor }}>{(stats.win_rate * 100).toFixed(1)}%</span>
        </div>
        <div className="flex justify-between text-xs">
          <span style={{ color: labelColor }}>{t('auto.PostLongRallyStats.k2')}</span>
          <span className="tabular-nums" style={{ color: valueColor }}>{stats.avg_rally_length.toFixed(1)}</span>
        </div>
        <div className="flex justify-between text-xs">
          <span style={{ color: labelColor }}>{t('auto.PostLongRallyStats.k3')}</span>
          <span className="tabular-nums" style={{ color: valueColor }}>{stats.count}</span>
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
          highlight="normal"
        />
        <ComparisonCard
          label={t('analysis.post_long_rally.post_long')}
          stats={data.post_long}
          highlight="post_long"
        />
      </div>

      {/* 差分表示 */}
      <div className="text-center text-sm">
        <span className="text-gray-400">{t('auto.PostLongRallyStats.k4')} </span>
        <span className="font-semibold" style={{ color: isPositive ? WIN : LOSS }}>
          {isPositive ? '+' : ''}{diffPct}%
        </span>
      </div>

      <p className="text-xs text-gray-500 text-center">
        ※ 10打以上のラリーを長ラリーとして判定
      </p>
    </div>
  )
}
