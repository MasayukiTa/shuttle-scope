// スコアフェーズ別パフォーマンスコンポーネント（序盤/中盤/終盤の3段棒グラフ）
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  BarChart,
  Bar,
  Cell,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { coolwarm, TOOLTIP_STYLE, AXIS_TICK } from '@/styles/colors'

interface TemporalPerformanceProps {
  playerId: number
}

interface PhaseData {
  phase: string
  win_rate: number
  rally_count: number
}

interface TemporalResponse {
  success: boolean
  data: { phases: PhaseData[] }
  meta: { sample_size: number; confidence: { level: string; stars: string; label: string } }
}

// 3フェーズをcoolwarmで等間隔サンプリング: 序盤=青, 中盤=白/中立, 終盤=赤
const PHASE_COLORS = [coolwarm(0), coolwarm(0.5), coolwarm(1)]

export function TemporalPerformance({ playerId }: TemporalPerformanceProps) {
  const { t } = useTranslation()

  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-temporal-performance', playerId],
    queryFn: () =>
      apiGet<TemporalResponse>('/analysis/temporal_performance', { player_id: playerId }),
    enabled: !!playerId,
  })

  if (isLoading) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.loading')}</div>
  }

  const phases = resp?.data?.phases ?? []
  const sampleSize = resp?.meta?.sample_size ?? 0

  if (phases.length === 0 || sampleSize === 0) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.no_data')}</div>
  }

  const chartData = phases.map((p, i) => ({
    name: p.phase,
    win_rate_pct: Math.round(p.win_rate * 100),
    rally_count: p.rally_count,
    color: PHASE_COLORS[i % PHASE_COLORS.length],
  }))

  return (
    <div className="space-y-3">
      <ConfidenceBadge sampleSize={sampleSize} />

      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={chartData} margin={{ top: 5, right: 16, left: 0, bottom: 5 }}>
          <XAxis
            dataKey="name"
            tick={{ fill: '#9ca3af', fontSize: 10 }}
            interval={0}
            height={40}
          />
          <YAxis
            tick={{ fill: '#9ca3af', fontSize: 10 }}
            domain={[0, 100]}
            tickFormatter={(v) => `${v}%`}
          />
          <Tooltip
            contentStyle={TOOLTIP_STYLE}
            formatter={(value: number, name: string) => [
              name === 'win_rate_pct' ? `${value}%` : value,
              name === 'win_rate_pct' ? t('analysis.temporal.win_rate') : t('analysis.temporal.rally_count'),
            ]}
          />
          {/* 50%の基準線 */}
          <ReferenceLine y={50} stroke="#6b7280" strokeDasharray="4 2" />
          <Bar
            dataKey="win_rate_pct"
            radius={[3, 3, 0, 0]}
            name={t('analysis.temporal.win_rate')}
          >
            {[0, 1, 2].map((i) => (
              <Cell key={i} fill={PHASE_COLORS[i]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>

      {/* フェーズ詳細テーブル */}
      <div className="space-y-1.5">
        {phases.map((p, i) => (
          <div key={p.phase} className="flex items-center justify-between text-xs">
            <span
              className="font-medium"
              style={{ color: PHASE_COLORS[i % PHASE_COLORS.length] }}
            >
              {p.phase}
            </span>
            <span className="text-gray-400">{p.rally_count}ラリー</span>
            <span className="text-white font-semibold">{(p.win_rate * 100).toFixed(1)}%</span>
          </div>
        ))}
      </div>
    </div>
  )
}
