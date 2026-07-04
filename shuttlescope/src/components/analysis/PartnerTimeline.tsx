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
    return <div className="text-[var(--ss-t3)] text-sm py-4 text-center">{t('analysis.loading')}</div>
  }

  const sampleSize = resp?.meta?.sample_size ?? 0
  const points = resp?.data?.points ?? []
  const overallWinRate = resp?.data?.overall_win_rate

  if (sampleSize === 0 || points.length === 0) {
    return <div className="text-[var(--ss-t3)] text-sm py-4 text-center">{t('analysis.no_data')}</div>
  }

  const chartData = points.map((p) => ({
    name: p.date.slice(5),
    fullDate: p.date.slice(2),
    cumulative: parseFloat((p.cumulative_win_rate * 100).toFixed(1)),
    result: p.result,
  }))

  const axisTick = isLight ? '#64748b' : '#9ca3af'
  const tooltipStyle = {
    backgroundColor: 'var(--ss-surface-1)',
    border: `1px solid var(--ss-border)`,
    color: 'var(--ss-t1)',
    borderRadius: '6px',
    fontSize: '11px',
  }

  return (
    <div className="space-y-2">
      <ConfidenceBadge sampleSize={sampleSize} />

      <div className="flex items-center justify-between">
        <span className="text-xs text-[var(--ss-t3)]">
          {partnerName ? `${partnerName}とのペア勝率推移` : 'ペア勝率推移'}
        </span>
        {overallWinRate != null && (
          <span className="text-xs font-semibold ss-num text-[var(--ss-brand)]">
            {t('auto.PartnerTimeline.overall', { pct: (overallWinRate * 100).toFixed(0) })} ({t('auto._shared.n_matches', { n: sampleSize })})
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
            labelFormatter={(label, payload) => {
              const p = payload as Array<{ payload?: { fullDate?: string } }> | undefined
              return p?.[0]?.payload?.fullDate ?? label
            }}
            formatter={(v: number) => [`${v}%`, '累積勝率']}
          />
          <Line
            type="monotone"
            dataKey="cumulative"
            stroke="var(--ss-brand)"
            strokeWidth={2}
            dot={{ r: 3, fill: 'var(--ss-brand)' }}
          />
        </LineChart>
      </ResponsiveContainer>

      {/* 試合結果の小さなドット列 */}
      <div className="flex gap-0.5 flex-wrap">
        {points.map((p) => (
          <div
            key={p.match_id}
            title={`${p.date} ${p.tournament} ${p.result === 'win' ? '勝' : '負'}`}
            className="w-2.5 h-2.5 rounded-ss-sm"
            style={{ backgroundColor: p.result === 'win' ? 'var(--ss-good)' : 'var(--ss-bad)', opacity: 0.8 }}
          />
        ))}
      </div>
    </div>
  )
}
