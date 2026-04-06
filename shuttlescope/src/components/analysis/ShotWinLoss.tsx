// ショット種別ごとの得点・失点を横棒積み上げグラフで表示するコンポーネント
import { useQuery } from '@tanstack/react-query'
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
import { WIN, LOSS, TOOLTIP_STYLE } from '@/styles/colors'
import { AnalysisFilters, DEFAULT_FILTERS } from '@/types'

interface ShotWinLossProps {
  playerId: number
  filters?: AnalysisFilters
}

interface ShotRow {
  shot_type: string
  shot_type_ja: string
  total: number
  win_count: number
  lose_count: number
  win_rate: number
}

interface ConfidenceMeta {
  level: 'low' | 'medium' | 'high'
  stars: string
  label: string
  warning?: string
}

interface ShotWinLossResponse {
  data: ShotRow[]
  meta: {
    sample_size: number
    confidence: ConfidenceMeta
  }
}

// カスタムツールチップ
function CustomTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  const win = payload.find((p: any) => p.dataKey === 'win_count')?.value ?? 0
  const lose = payload.find((p: any) => p.dataKey === 'lose_count')?.value ?? 0
  const total = win + lose
  const rate = total > 0 ? ((win / total) * 100).toFixed(1) : '0.0'
  return (
    <div style={TOOLTIP_STYLE} className="px-3 py-2">
      <p className="font-semibold mb-1" style={{ color: '#f9fafb' }}>{label}</p>
      <p style={{ color: WIN }}>得点: {win}</p>
      <p style={{ color: LOSS }}>失点: {lose}</p>
      <p style={{ color: '#d1d5db' }}>勝率: {rate}%</p>
    </div>
  )
}

export function ShotWinLoss({ playerId, filters = DEFAULT_FILTERS }: ShotWinLossProps) {
  const fp = {
    ...(filters.result !== 'all' ? { result: filters.result } : {}),
    ...(filters.tournamentLevel ? { tournament_level: filters.tournamentLevel } : {}),
    ...(filters.dateFrom ? { date_from: filters.dateFrom } : {}),
    ...(filters.dateTo ? { date_to: filters.dateTo } : {}),
  }
  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-shot-win-loss', playerId, filters],
    queryFn: () =>
      apiGet<ShotWinLossResponse>('/analysis/shot_win_loss', { player_id: playerId, ...fp }),
    enabled: !!playerId,
  })

  if (isLoading) {
    return (
      <div className="text-gray-500 text-sm py-8 text-center">読み込み中...</div>
    )
  }

  const rows = resp?.data ?? []
  const sampleSize = resp?.meta?.sample_size ?? 0

  // データが空またはサンプル不足
  if (rows.length === 0 || sampleSize === 0) {
    return (
      <div className="text-gray-500 text-sm py-4 text-center">
        データ不足（アノテーション後に解析可能）
      </div>
    )
  }

  // recharts用にデータ整形（shot_type_ja を name として使用）
  const chartData = rows.map((r) => ({
    name: r.shot_type_ja || r.shot_type,
    win_count: r.win_count,
    lose_count: r.lose_count,
    win_rate: r.win_rate,
    total: r.total,
  }))

  const chartHeight = Math.max(160, chartData.length * 38)

  return (
    <div className="space-y-3">
      {/* 信頼度バッジ */}
      <ConfidenceBadge sampleSize={sampleSize} />

      {/* 積み上げ横棒グラフ */}
      <ResponsiveContainer width="100%" height={chartHeight}>
        <BarChart
          data={chartData}
          layout="vertical"
          margin={{ top: 0, right: 72, left: 8, bottom: 0 }}
          barCategoryGap="25%"
        >
          <XAxis
            type="number"
            tick={{ fill: '#9ca3af', fontSize: 11 }}
            allowDecimals={false}
          />
          <YAxis
            type="category"
            dataKey="name"
            width={88}
            tick={{ fill: '#d1d5db', fontSize: 11 }}
          />
          <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
          {/* 得点 (WIN=coolwarm低端青) */}
          <Bar dataKey="win_count" stackId="wl" fill={WIN} name="得点" radius={[0, 0, 0, 0]}>
            {chartData.map((_, i) => <Cell key={i} fill={WIN} />)}
          </Bar>
          {/* 失点 (LOSS=coolwarm高端赤) */}
          <Bar dataKey="lose_count" stackId="wl" fill={LOSS} name="失点" radius={[0, 3, 3, 0]}>
            {chartData.map((_, i) => <Cell key={i} fill={LOSS} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>

      {/* 勝率リスト */}
      <div className="space-y-1">
        {chartData.map((d) => {
          const ratePct = (d.win_rate * 100).toFixed(1)
          const barWidth = `${Math.min(d.win_rate * 100, 100).toFixed(1)}%`
          return (
            <div key={d.name} className="flex items-center gap-2 text-xs">
              <span className="w-[88px] shrink-0 text-gray-400 truncate">{d.name}</span>
              <div className="flex-1 bg-gray-700 rounded-full h-1.5 min-w-0">
                <div
                  className="h-1.5 rounded-full transition-all"
                  style={{ width: barWidth, backgroundColor: WIN }}
                />
              </div>
              <span className="w-10 text-right text-gray-300 shrink-0">{ratePct}%</span>
            </div>
          )
        })}
      </div>

      {/* 凡例 */}
      <div className="flex gap-4 text-xs text-gray-400 pt-1">
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-3 h-3 rounded-sm" style={{ backgroundColor: WIN }} />
          得点
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-3 h-3 rounded-sm" style={{ backgroundColor: LOSS }} />
          失点
        </span>
      </div>
    </div>
  )
}
