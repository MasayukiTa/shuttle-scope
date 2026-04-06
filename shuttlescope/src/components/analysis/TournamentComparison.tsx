// 大会レベル別比較コンポーネント（棒グラフ + テーブル）
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { perfColor, TOOLTIP_STYLE } from '@/styles/colors'
import { AnalysisFilters, DEFAULT_FILTERS } from '@/types'

interface TournamentComparisonProps {
  playerId: number
  filters?: AnalysisFilters
}

interface LevelData {
  level: string
  match_count: number
  win_rate: number
  avg_rally_length: number
  sample_size: number
}

interface TournamentResponse {
  success: boolean
  data: { levels: LevelData[] }
  meta: {
    sample_size: number
    confidence: { level: string; stars: string; label: string }
  }
}

export function TournamentComparison({ playerId, filters = DEFAULT_FILTERS }: TournamentComparisonProps) {
  const { t } = useTranslation()

  const fp = {
    ...(filters.result !== 'all' ? { result: filters.result } : {}),
    ...(filters.tournamentLevel ? { tournament_level: filters.tournamentLevel } : {}),
    ...(filters.dateFrom ? { date_from: filters.dateFrom } : {}),
    ...(filters.dateTo ? { date_to: filters.dateTo } : {}),
  }
  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-tournament-comparison', playerId, filters],
    queryFn: () =>
      apiGet<TournamentResponse>('/analysis/tournament_level_comparison', { player_id: playerId, ...fp }),
    enabled: !!playerId,
  })

  if (isLoading) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.loading')}</div>
  }

  const levels = resp?.data?.levels ?? []
  const sampleSize = resp?.meta?.sample_size ?? 0

  if (levels.length === 0) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.no_data')}</div>
  }

  const chartData = levels.map((l) => ({
    name: l.level,
    win_rate: Math.round(l.win_rate * 100),
    match_count: l.match_count,
  }))

  return (
    <div className="space-y-3">
      <ConfidenceBadge sampleSize={sampleSize} />

      {/* 棒グラフ */}
      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={chartData} margin={{ top: 5, right: 16, left: 0, bottom: 5 }}>
          <XAxis dataKey="name" tick={{ fill: '#9ca3af', fontSize: 11 }} />
          <YAxis
            tick={{ fill: '#9ca3af', fontSize: 11 }}
            domain={[0, 100]}
            tickFormatter={(v) => `${v}%`}
          />
          <Tooltip
            contentStyle={TOOLTIP_STYLE}
            formatter={(value: number) => [`${value}%`, t('analysis.tournament_comparison.win_rate')]}
          />
          <Bar dataKey="win_rate" radius={[3, 3, 0, 0]} name={t('analysis.tournament_comparison.win_rate')}>
            {chartData.map((entry) => (
              <Cell key={entry.name} fill={perfColor(entry.win_rate / 100)} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>

      {/* テーブル */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-gray-400 border-b border-gray-700">
              <th className="text-left py-1.5 pr-3">{t('analysis.tournament_comparison.level')}</th>
              <th className="text-center py-1.5 pr-3">{t('analysis.tournament_comparison.match_count')}</th>
              <th className="text-center py-1.5 pr-3">{t('analysis.tournament_comparison.win_rate')}</th>
              <th className="text-right py-1.5">{t('analysis.tournament_comparison.avg_rally')}</th>
            </tr>
          </thead>
          <tbody>
            {levels.map((l) => (
              <tr key={l.level} className="border-b border-gray-700/40 hover:bg-gray-700/20">
                <td className="py-1.5 pr-3 font-medium" style={{ color: perfColor(l.win_rate) }}>
                  {l.level}
                </td>
                <td className="py-1.5 pr-3 text-center text-gray-300">{l.match_count}</td>
                <td className="py-1.5 pr-3 text-center text-white font-semibold">
                  {(l.win_rate * 100).toFixed(1)}%
                </td>
                <td className="py-1.5 text-right text-gray-300">{l.avg_rally_length.toFixed(1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
