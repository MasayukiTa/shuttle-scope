// Phase 2: 成長タイムライン（試合軸×指標のLineChart + 移動平均）
// partnerPlayerId を指定するとペア比較モード（2ライン表示）
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
  playerName?: string
  metric?: Metric
  windowSize?: number
  /** 指定するとペア比較モード（2ライン）になる */
  partnerPlayerId?: number | null
  partnerName?: string
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
    weighted_trend?: 'improving' | 'stable' | 'declining' | 'pending'
    weighted_trend_delta?: number
  }
  meta: { sample_size: number; confidence: { level: string; stars: string; label: string } }
}

const METRIC_CONFIG: Record<Metric, { label: string; colorA: string; colorB: string; unit: string; domain: [number | 'auto', number | 'auto'] }> = {
  win_rate:         { label: '勝率',         colorA: '#3b82f6', colorB: '#f97316', unit: '%',  domain: [0, 1] },
  serve_win_rate:   { label: 'サーブ勝率',   colorA: '#06b6d4', colorB: '#a855f7', unit: '%',  domain: [0, 1] },
  avg_rally_length: { label: '平均ラリー長', colorA: '#8b5cf6', colorB: '#10b981', unit: '球', domain: ['auto', 'auto'] },
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

// ISO 日付を軸ラベル用に変換（年変わり目は '25 形式）
function toChartName(date: string, prevDate: string | null): { name: string; isYearBoundary: boolean } {
  const year = date.slice(0, 4)
  const prevYear = prevDate ? prevDate.slice(0, 4) : year
  const isYearBoundary = !!prevDate && year !== prevYear
  return {
    name: isYearBoundary ? `'${year.slice(2)}` : date.slice(5),
    isYearBoundary,
  }
}

export function GrowthTimeline({
  playerId,
  playerName,
  metric = 'win_rate',
  windowSize = 3,
  partnerPlayerId,
  partnerName,
}: GrowthTimelineProps) {
  const { t } = useTranslation()
  const isLight = useIsLightMode()
  const isPairMode = !!partnerPlayerId

  // メインプレイヤーのクエリ
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

  // 相方のクエリ（ペアモード時のみ）
  const { data: partnerResp, isLoading: partnerLoading } = useQuery({
    queryKey: ['analysis-growth-timeline', partnerPlayerId, metric, windowSize],
    queryFn: () =>
      apiGet<GrowthTimelineResponse>('/analysis/growth_timeline', {
        player_id: partnerPlayerId!,
        metric,
        window_size: windowSize,
      }),
    enabled: isPairMode && !!partnerPlayerId,
  })

  if (isLoading || (isPairMode && partnerLoading)) {
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

  // ─── ペアモード: 日付をキーにして2プレイヤーのデータをマージ ─────────────

  let chartData: Record<string, any>[]
  let yearBoundaryNames: string[]

  if (isPairMode && partnerResp) {
    const partnerPoints = partnerResp.data?.points ?? []

    // 全日付を union して時系列順にソート
    const allDates = Array.from(
      new Set([...points.map((p) => p.date), ...partnerPoints.map((p) => p.date)])
    ).sort()

    const mapA = new Map(points.map((p) => [p.date, p]))
    const mapB = new Map(partnerPoints.map((p) => [p.date, p]))

    chartData = allDates.map((date, i) => {
      const prevDate = i > 0 ? allDates[i - 1] : null
      const { name, isYearBoundary } = toChartName(date, prevDate)
      const pA = mapA.get(date)
      const pB = mapB.get(date)
      return {
        name,
        isYearBoundary,
        fullDate: date.slice(2),
        valueA: pA ? (isRate ? parseFloat((pA.value * 100).toFixed(1)) : pA.value) : null,
        movingAvgA: pA?.moving_avg != null ? (isRate ? parseFloat((pA.moving_avg * 100).toFixed(1)) : pA.moving_avg) : null,
        valueB: pB ? (isRate ? parseFloat((pB.value * 100).toFixed(1)) : pB.value) : null,
        movingAvgB: pB?.moving_avg != null ? (isRate ? parseFloat((pB.moving_avg * 100).toFixed(1)) : pB.moving_avg) : null,
      }
    })
    yearBoundaryNames = chartData.filter((d) => d.isYearBoundary).map((d) => d.name)
  } else {
    // 通常モード（従来通り）
    chartData = points.map((p, i) => {
      const prevDate = i > 0 ? points[i - 1].date : null
      const { name, isYearBoundary } = toChartName(p.date, prevDate)
      return {
        name,
        isYearBoundary,
        fullDate: p.date.slice(2),
        value: isRate ? parseFloat((p.value * 100).toFixed(1)) : p.value,
        moving_avg: p.moving_avg != null ? (isRate ? parseFloat((p.moving_avg * 100).toFixed(1)) : p.moving_avg) : null,
      }
    })
    yearBoundaryNames = chartData.filter((d) => d.isYearBoundary).map((d) => d.name)
  }

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

  const labelA = playerName ?? 'A'
  const labelB = partnerName ?? 'B'

  return (
    <div className="space-y-2">
      <ConfidenceBadge sampleSize={sampleSize} />

      {/* トレンドラベル（メインプレイヤー） */}
      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-400">{cfg.label}</span>
        {!isPairMode && (
          <span className="text-xs font-semibold" style={{ color: trendColor }}>
            {TREND_LABELS[trend]}
            {trend !== 'pending' && (
              <span className="ml-1 font-mono">
                ({trendDelta >= 0 ? '+' : ''}{isRate ? (trendDelta * 100).toFixed(1) : trendDelta.toFixed(2)}{cfg.unit})
              </span>
            )}
          </span>
        )}
        {isPairMode && (
          <div className="flex items-center gap-3 text-[10px]">
            <span className="flex items-center gap-1">
              <span className="inline-block w-3 h-0.5 rounded" style={{ backgroundColor: cfg.colorA }} />
              {labelA}
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block w-3 h-0.5 rounded" style={{ backgroundColor: cfg.colorB }} />
              {labelB}
            </span>
          </div>
        )}
      </div>

      <ResponsiveContainer width="100%" height={180}>
        <LineChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: -20 }}>
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
            labelFormatter={(label, payload: any) => payload?.[0]?.payload?.fullDate ?? label}
            formatter={(v: number, name: string) => {
              if (name === 'valueA') return [`${v}${cfg.unit}`, labelA]
              if (name === 'movingAvgA') return [`${v}${cfg.unit}`, `${labelA} 移動平均`]
              if (name === 'valueB') return [`${v}${cfg.unit}`, labelB]
              if (name === 'movingAvgB') return [`${v}${cfg.unit}`, `${labelB} 移動平均`]
              if (name === 'value') return [`${v}${cfg.unit}`, cfg.label]
              return [`${v}${cfg.unit}`, `移動平均(${windowSize}試合)`]
            }}
          />
          {yearBoundaryNames.map((name) => (
            <ReferenceLine
              key={name}
              x={name}
              stroke={gridColor}
              strokeDasharray="3 2"
              strokeWidth={1}
              label={{ value: name, position: 'insideTopRight', fontSize: 8, fill: axisTick }}
            />
          ))}

          {isPairMode ? (
            <>
              {/* プレイヤーA */}
              <Line type="monotone" dataKey="valueA" stroke={cfg.colorA} strokeWidth={1.5}
                dot={{ r: 3, fill: cfg.colorA }} connectNulls name="valueA" />
              <Line type="monotone" dataKey="movingAvgA" stroke={cfg.colorA} strokeWidth={2.5}
                strokeDasharray="4 2" dot={false} connectNulls name="movingAvgA" />
              {/* プレイヤーB（相方） */}
              <Line type="monotone" dataKey="valueB" stroke={cfg.colorB} strokeWidth={1.5}
                dot={{ r: 3, fill: cfg.colorB }} connectNulls name="valueB" />
              <Line type="monotone" dataKey="movingAvgB" stroke={cfg.colorB} strokeWidth={2.5}
                strokeDasharray="4 2" dot={false} connectNulls name="movingAvgB" />
            </>
          ) : (
            <>
              <Line type="monotone" dataKey="value" stroke={cfg.colorA} strokeWidth={1.5}
                dot={{ r: 3, fill: cfg.colorA }} name="value" />
              <Line type="monotone" dataKey="moving_avg" stroke={cfg.colorA} strokeWidth={2.5}
                strokeDasharray="4 2" dot={false} connectNulls name="moving_avg" />
            </>
          )}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
