// セット別（1・2・3セット目）の勝率と平均ラリー長を縦棒グラフで表示
import { useQuery } from '@tanstack/react-query'
import {
  BarChart,
  Bar,
  Cell,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'

interface SetComparisonProps {
  playerId: number
}

interface SetData {
  set_number: number     // 1, 2, 3
  label: string          // "第1セット" 等
  total_rallies: number
  win_rate: number
  avg_rally_length: number
}

interface SetComparisonResponse {
  data: SetData[]
  meta: {
    sample_size: number
    confidence: { level: string; stars: string; label: string; warning?: string }
  }
}

const TOOLTIP_STYLE = {
  backgroundColor: '#1f2937',
  border: '1px solid #374151',
  borderRadius: '6px',
  color: '#f9fafb',
  fontSize: 12,
}

function CustomTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  const winRate = payload.find((p: any) => p.dataKey === 'win_rate_pct')?.value ?? 0
  const avgRally = payload.find((p: any) => p.dataKey === 'avg_rally_length')?.value ?? 0
  return (
    <div style={TOOLTIP_STYLE} className="px-3 py-2">
      <p className="font-semibold text-white mb-1">{label}</p>
      <p className="text-blue-300">勝率: {typeof winRate === 'number' ? winRate.toFixed(1) : winRate}%</p>
      <p className="text-gray-300">平均ラリー長: {typeof avgRally === 'number' ? avgRally.toFixed(1) : avgRally}</p>
    </div>
  )
}

// 勝率バーの色（セット番号で変える）
const SET_COLORS = ['#3b82f6', '#8b5cf6', '#f59e0b']

export function SetComparison({ playerId }: SetComparisonProps) {
  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-set-comparison', playerId],
    queryFn: () =>
      apiGet<SetComparisonResponse>('/analysis/set_comparison', {
        player_id: playerId,
      }),
    enabled: !!playerId,
  })

  if (isLoading) {
    return (
      <div className="text-gray-500 text-sm py-8 text-center">読み込み中...</div>
    )
  }

  const sets = resp?.data ?? []
  const sampleSize = resp?.meta?.sample_size ?? 0

  if (sets.length === 0 || sampleSize === 0) {
    return (
      <div className="text-gray-500 text-sm py-4 text-center">
        データ不足（アノテーション後に解析可能）
      </div>
    )
  }

  const chartData = sets.map((s) => ({
    name: s.label || `第${s.set_number}セット`,
    win_rate_pct: +(s.win_rate * 100).toFixed(1),
    avg_rally_length: +s.avg_rally_length.toFixed(1),
    total_rallies: s.total_rallies,
  }))

  return (
    <div className="space-y-3">
      {/* 信頼度バッジ */}
      <ConfidenceBadge sampleSize={sampleSize} />

      {/* 勝率縦棒グラフ */}
      <ResponsiveContainer width="100%" height={200}>
        <BarChart
          data={chartData}
          margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
          barCategoryGap="35%"
        >
          <XAxis dataKey="name" tick={{ fill: '#9ca3af', fontSize: 12 }} />
          <YAxis
            domain={[0, 100]}
            tickFormatter={(v) => `${v}%`}
            tick={{ fill: '#9ca3af', fontSize: 11 }}
          />
          <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
          <Bar dataKey="win_rate_pct" radius={[4, 4, 0, 0]} name="勝率">
            {chartData.map((_, i) => (
              <Cell key={i} fill={SET_COLORS[i % SET_COLORS.length]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>

      {/* 統計サマリーカード */}
      <div className="grid grid-cols-3 gap-2">
        {sets.map((s, i) => (
          <div
            key={s.set_number}
            className="bg-gray-700/30 rounded-lg px-3 py-2 text-center"
          >
            <p className="text-xs text-gray-400 mb-1">
              {s.label || `第${s.set_number}セット`}
            </p>
            <p
              className="text-lg font-bold"
              style={{ color: SET_COLORS[i % SET_COLORS.length] }}
            >
              {(s.win_rate * 100).toFixed(1)}%
            </p>
            <p className="text-xs text-gray-500 mt-0.5">
              平均 {s.avg_rally_length.toFixed(1)} 打
            </p>
            <p className="text-xs text-gray-600">
              {s.total_rallies} ラリー
            </p>
          </div>
        ))}
      </div>
    </div>
  )
}
