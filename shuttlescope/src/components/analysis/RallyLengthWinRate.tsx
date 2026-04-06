// ラリー長区間別勝率を棒グラフ（件数）＋折れ線（勝率）のコンポーズドチャートで表示
import { useQuery } from '@tanstack/react-query'
import {
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Area,
} from 'recharts'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { BAR, LINE, TOOLTIP_STYLE, AXIS_TICK } from '@/styles/colors'
import { AnalysisFilters, DEFAULT_FILTERS } from '@/types'

interface RallyLengthWinRateProps {
  playerId: number
  chartHeight?: number
  filters?: AnalysisFilters
}

interface RallyBucket {
  bucket_label: string   // "1-3打" 等
  count: number
  win_count: number
  win_rate: number
}

interface PlayerTypeInfo {
  type_key: string       // "short_specialist" 等
  type_label: string     // "短期決戦型" 等
  description?: string
}

interface RallyLengthResponse {
  data: {
    buckets: RallyBucket[]
    player_type?: PlayerTypeInfo
  }
  meta: {
    sample_size: number
    confidence: { level: string; stars: string; label: string; warning?: string }
  }
}

// プレイヤータイプごとのバッジ色
function playerTypeBadgeClass(typeKey: string): string {
  switch (typeKey) {
    case 'short_specialist':
      return 'bg-orange-900/40 border-orange-500 text-orange-300'
    case 'long_specialist':
      return 'bg-purple-900/40 border-purple-500 text-purple-300'
    case 'balanced':
      return 'bg-green-900/40 border-green-500 text-green-300'
    default:
      return 'bg-gray-700 border-gray-500 text-gray-300'
  }
}

// カスタムツールチップ
function CustomTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  const count = payload.find((p: any) => p.dataKey === 'count')?.value ?? 0
  const winRate = payload.find((p: any) => p.dataKey === 'win_rate_pct')?.value ?? 0
  return (
    <div style={TOOLTIP_STYLE} className="px-3 py-2">
      <p className="font-semibold text-white mb-1">{label}</p>
      <p className="text-blue-300">件数: {count}</p>
      <p className="text-emerald-300">勝率: {typeof winRate === 'number' ? winRate.toFixed(1) : winRate}%</p>
    </div>
  )
}

export function RallyLengthWinRate({ playerId, chartHeight = 220, filters = DEFAULT_FILTERS }: RallyLengthWinRateProps) {
  const fp = {
    ...(filters.result !== 'all' ? { result: filters.result } : {}),
    ...(filters.tournamentLevel ? { tournament_level: filters.tournamentLevel } : {}),
    ...(filters.dateFrom ? { date_from: filters.dateFrom } : {}),
    ...(filters.dateTo ? { date_to: filters.dateTo } : {}),
  }
  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-rally-length-win-rate', playerId, filters],
    queryFn: () =>
      apiGet<RallyLengthResponse>('/analysis/rally_length_vs_winrate', {
        player_id: playerId,
        ...fp,
      }),
    enabled: !!playerId,
  })

  if (isLoading) {
    return (
      <div className="text-gray-500 text-sm py-8 text-center">読み込み中...</div>
    )
  }

  const buckets = resp?.data?.buckets ?? []
  const playerType = resp?.data?.player_type
  const sampleSize = resp?.meta?.sample_size ?? 0

  if (buckets.length === 0 || sampleSize === 0) {
    return (
      <div className="text-gray-500 text-sm py-4 text-center">
        データ不足（アノテーション後に解析可能）
      </div>
    )
  }

  // 勝率を % に変換してチャートデータを作成
  const chartData = buckets.map((b) => ({
    name: b.bucket_label,
    count: b.count,
    win_rate_pct: +(b.win_rate * 100).toFixed(1),
  }))

  return (
    <div className="space-y-3">
      {/* 信頼度バッジ + プレイヤータイプバッジ */}
      <div className="flex flex-wrap items-center gap-2">
        <ConfidenceBadge sampleSize={sampleSize} />
        {playerType && (
          <span
            className={`inline-flex items-center px-2 py-1 rounded border text-xs font-medium ${playerTypeBadgeClass(
              playerType.type_key
            )}`}
          >
            {playerType.type_label}
          </span>
        )}
      </div>

      {/* コンポーズドチャート */}
      <ResponsiveContainer width="100%" height={chartHeight}>
        <ComposedChart
          data={chartData}
          margin={{ top: 8, right: 40, left: 0, bottom: 0 }}
        >
          <XAxis dataKey="name" tick={{ fill: '#9ca3af', fontSize: 11 }} />
          {/* 左 Y 軸: 件数 */}
          <YAxis
            yAxisId="count"
            orientation="left"
            tick={{ fill: '#9ca3af', fontSize: 11 }}
            allowDecimals={false}
          />
          {/* 右 Y 軸: 勝率 % */}
          <YAxis
            yAxisId="rate"
            orientation="right"
            domain={[0, 100]}
            tickFormatter={(v) => `${v}%`}
            tick={{ fill: '#9ca3af', fontSize: 11 }}
          />
          <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
          <Bar
            yAxisId="count"
            dataKey="count"
            fill={BAR}
            radius={[3, 3, 0, 0]}
            name="件数"
            opacity={0.75}
          />
          <Line
            yAxisId="rate"
            type="monotone"
            dataKey="win_rate_pct"
            stroke={LINE}
            strokeWidth={2}
            dot={{ fill: LINE, r: 4 }}
            name="勝率"
          />
        </ComposedChart>
      </ResponsiveContainer>

      {/* 凡例 */}
      <div className="flex gap-4 text-xs text-gray-400">
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-3 h-3 rounded-sm opacity-75" style={{ backgroundColor: BAR }} />
          件数
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-3 h-0.5" style={{ backgroundColor: LINE }} />
          勝率
        </span>
      </div>
    </div>
  )
}
