// Phase 2: 成長タイムライン（試合軸×指標のLineChart + 移動平均）
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, Legend,
} from 'recharts'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { NoDataMessage } from '@/components/common/NoDataMessage'
import { useIsLightMode } from '@/hooks/useIsLightMode'

type Metric = 'win_rate' | 'avg_rally_length' | 'serve_win_rate'

interface GrowthTimelineProps {
  playerId: number
  metric?: Metric
  windowSize?: number
}

interface TimelinePoint {
  match_id: number
  date: string
  value: number
  moving_avg: number | null
}

interface GrowthTimelineResponse {
  success: boolean
  data: {
    points: TimelinePoint[]
    trend: 'improving' | 'stable' | 'declining' | 'pending'
    trend_delta: number
  }
  meta: { sample_size: number; confidence: { level: string; stars: string; label: string } }
}

const METRIC_CONFIG: Record<Metric, { label: string; color: string; unit: string; domain: [number | 'auto', number | 'auto'] }> = {
  win_rate:         { label: '勝率',         color: '#3b82f6', unit: '%',  domain: [0, 1] },
  serve_win_rate:   { label: 'サーブ勝率',   color: '#06b6d4', unit: '%',  domain: [0, 1] },
  avg_rally_length: { label: '平均ラリー長', color: '#8b5cf6', unit: '球', domain: ['auto', 'auto'] },
}

const TREND_LABELS = {
  improving: '改善傾向',
  stable:    '横ばい',
  declining: '悪化傾向',
  pending:   '判定保留',
}

const TREND_COLORS = {
  improving: '#3b82f6',
  stable:    '#6b7280',
  declining: '#ef4444',
  pending:   '#eab308',
}

export function GrowthTimeline({ playerId, metric = 'win_rate', windowSize = 3 }: GrowthTimelineProps) {
  const { t } = useTranslation()
  const isLight = useIsLightMode()

  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-growth-timeline', playerId, metric, windowSize],
    queryFn: () =>
      apiGet<GrowthTimelineResponse>('/analysis/growth_timeline', {
        player_id: playerId,
        metric,
        window_size: windowSize,
      }),
    enabled: !!playerId,
  })

  if (isLoading) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.loading')}</div>
  }

  const sampleSize = resp?.meta?.sample_size ?? 0
  const points = resp?.data?.points ?? []
  const trend = resp?.data?.trend ?? 'pending'
  const trendDelta = resp?.data?.trend_delta ?? 0

  if (sampleSize === 0 || points.length === 0) {
    return <NoDataMessage sampleSize={sampleSize} minRequired={3} unit="試合" />
  }

  const cfg = METRIC_CONFIG[metric]
  const isRate = metric !== 'avg_rally_length'

  // チャートデータ整形
  const chartData = points.map((p) => ({
    name: p.date.slice(5), // MM-DD 表示
    value: isRate ? parseFloat((p.value * 100).toFixed(1)) : p.value,
    moving_avg: p.moving_avg != null ? (isRate ? parseFloat((p.moving_avg * 100).toFixed(1)) : p.moving_avg) : null,
  }))

  const trendColor = TREND_COLORS[trend] ?? TREND_COLORS.pending
  const axisTick = isLight ? '#64748b' : '#9ca3af'
  const gridColor = isLight ? '#e2e8f0' : '#374151'

  const tooltipStyle = {
    backgroundColor: isLight ? '#ffffff' : '#1f2937',
    border: `1px solid ${isLight ? '#e2e8f0' : '#374151'}`,
    color: isLight ? '#1e293b' : '#f1f5f9',
    borderRadius: '6px',
    fontSize: '11px',
  }

  return (
    <div className="space-y-2">
      <ConfidenceBadge sampleSize={sampleSize} />

      {/* トレンドラベル */}
      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-400">{cfg.label}</span>
        <span className="text-xs font-semibold" style={{ color: trendColor }}>
          {TREND_LABELS[trend]}
          {trend !== 'pending' && (
            <span className="ml-1 font-mono">
              ({trendDelta >= 0 ? '+' : ''}{isRate ? (trendDelta * 100).toFixed(1) : trendDelta.toFixed(2)}{cfg.unit})
            </span>
          )}
        </span>
      </div>

      <ResponsiveContainer width="100%" height={160}>
        <LineChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
          <XAxis dataKey="name" tick={{ fill: axisTick, fontSize: 9 }} tickLine={false} axisLine={false} />
          <YAxis
            tick={{ fill: axisTick, fontSize: 9 }}
            tickLine={false}
            axisLine={false}
            domain={isRate ? [0, 100] : cfg.domain}
            tickFormatter={(v) => isRate ? `${v}%` : String(v)}
          />
          <Tooltip
            contentStyle={tooltipStyle}
            formatter={(v: number, name: string) => [
              `${v}${cfg.unit}`,
              name === 'value' ? cfg.label : `移動平均(${windowSize}試合)`,
            ]}
          />
          <Line
            type="monotone"
            dataKey="value"
            stroke={cfg.color}
            strokeWidth={1.5}
            dot={{ r: 3, fill: cfg.color }}
            name="value"
          />
          <Line
            type="monotone"
            dataKey="moving_avg"
            stroke={cfg.color}
            strokeWidth={2.5}
            strokeDasharray="4 2"
            dot={false}
            connectNulls
            name="moving_avg"
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
