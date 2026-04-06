// Phase 2: ペア別勝率推移タイムライン
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
} from 'recharts'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { useIsLightMode } from '@/hooks/useIsLightMode'

interface PartnerTimelineProps {
  playerId: number
  partnerId: number
  partnerName?: string
}

interface TimelinePoint {
  match_id: number
  date: string
  result: 'win' | 'loss'
  cumulative_win_rate: number
  tournament: string
}

interface PartnerTimelineResponse {
  success: boolean
  data: {
    points: TimelinePoint[]
    overall_win_rate: number | null
  }
  meta: { sample_size: number; confidence: { level: string; stars: string; label: string } }
}

export function PartnerTimeline({ playerId, partnerId, partnerName }: PartnerTimelineProps) {
  const { t } = useTranslation()
  const isLight = useIsLightMode()

  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-partner-timeline', playerId, partnerId],
    queryFn: () =>
      apiGet<PartnerTimelineResponse>('/analysis/partner_timeline', {
        player_id: playerId,
        partner_id: partnerId,
      }),
    enabled: !!playerId && !!partnerId,
  })

  if (isLoading) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.loading')}</div>
  }

  const sampleSize = resp?.meta?.sample_size ?? 0
  const points = resp?.data?.points ?? []
  const overallWinRate = resp?.data?.overall_win_rate

  if (sampleSize === 0 || points.length === 0) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.no_data')}</div>
  }

  const chartData = points.map((p) => ({
    name: p.date.slice(5),
    cumulative: parseFloat((p.cumulative_win_rate * 100).toFixed(1)),
    result: p.result,
  }))

  const axisTick = isLight ? '#64748b' : '#9ca3af'
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

      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-400">
          {partnerName ? `${partnerName}とのペア勝率推移` : 'ペア勝率推移'}
        </span>
        {overallWinRate != null && (
          <span className="text-xs font-semibold text-blue-400">
            通算 {(overallWinRate * 100).toFixed(0)}% ({sampleSize}試合)
          </span>
        )}
      </div>

      <ResponsiveContainer width="100%" height={140}>
        <LineChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
          <XAxis dataKey="name" tick={{ fill: axisTick, fontSize: 9 }} tickLine={false} axisLine={false} />
          <YAxis
            tick={{ fill: axisTick, fontSize: 9 }}
            tickLine={false}
            axisLine={false}
            domain={[0, 100]}
            tickFormatter={(v) => `${v}%`}
          />
          <Tooltip
            contentStyle={tooltipStyle}
            formatter={(v: number) => [`${v}%`, '累積勝率']}
          />
          <Line
            type="monotone"
            dataKey="cumulative"
            stroke="#06b6d4"
            strokeWidth={2}
            dot={{ r: 3, fill: '#06b6d4' }}
          />
        </LineChart>
      </ResponsiveContainer>

      {/* 試合結果の小さなドット列 */}
      <div className="flex gap-0.5 flex-wrap">
        {points.map((p) => (
          <div
            key={p.match_id}
            title={`${p.date} ${p.tournament} ${p.result === 'win' ? '勝' : '負'}`}
            className="w-2.5 h-2.5 rounded-sm"
            style={{ backgroundColor: p.result === 'win' ? '#3b82f6' : '#ef4444', opacity: 0.8 }}
          />
        ))}
      </div>
    </div>
  )
}
