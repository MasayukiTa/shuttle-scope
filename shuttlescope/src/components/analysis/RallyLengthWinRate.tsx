// ラリー長区間別勝率を棒グラフ（件数）＋折れ線（勝率）のコンポーズドチャートで表示
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  } from 'recharts'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { BAR, LINE, getTooltipStyle } from '@/styles/colors'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { AnalysisFilters, DEFAULT_FILTERS } from '@/types'

interface RallyLengthWinRateProps {
  playerId: number
  chartHeight?: number
  filters?: AnalysisFilters
}

interface RallyBucket {
  // backend (analysis_advanced.get_rally_length_vs_winrate) の契約名は range ("1-3" 等)。
  // 旧コードは存在しない bucket_label だけを読み、X 軸ラベルが全て空になっていた。
  range?: string
  bucket_label?: string
  count: number
  win_count?: number
  // 件数 0 の区間は null (0% ではない)
  win_rate: number | null
}

interface PlayerTypeInfo {
  type_key: string       // "short_specialist" 等
  type_label: string     // "短期決戦型" 等
  description?: string
}

interface RallyLengthResponse {
  data: {
    buckets: RallyBucket[]
    // backend は player_type を文字列 (キー) で、日本語名を player_type_ja で返す
    player_type?: PlayerTypeInfo | string
    player_type_ja?: string
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
    case 'short_game_specialist':
      return 'bg-gray-800 border-gray-700 text-amber-400'
    case 'long_specialist':
    case 'endurance_player':
      return 'bg-gray-800 border-gray-700 text-gray-200'
    case 'balanced':
      return 'bg-gray-800 border-gray-700 text-blue-300'
    default:
      return 'bg-gray-700 border-gray-500 text-gray-300'
  }
}

// カスタムツールチップ
function CustomTooltip({ active, payload, label }: import('@/utils/rechartsTypes').RechartsTooltipProps) {
  const { t } = useTranslation()

  const isLight = useIsLightMode()
  if (!active || !payload?.length) return null
  const count = payload.find((p) => p.dataKey === 'count')?.value ?? 0
  const winRate = payload.find((p) => p.dataKey === 'win_rate_pct')?.value
  const headingColor = isLight ? '#0f172a' : '#f9fafb'
  return (
    <div style={getTooltipStyle(isLight)} className="px-3 py-2">
      <p className="font-semibold mb-1" style={{ color: headingColor }}>{label}</p>
      <p className="ss-num" style={{ color: BAR }}>{t('auto.RallyLengthWinRate.count', { n: count })}</p>
      <p className="ss-num" style={{ color: LINE }}>
        {typeof winRate === 'number' ? t('auto.RallyLengthWinRate.win_rate', { v: winRate.toFixed(1) }) : `${t('auto.RallyLengthWinRate.rate_legend')}: ${t('auto.RallyLengthWinRate.no_data')}`}
      </p>
    </div>
  )
}

// backend は player_type を文字列キーで、日本語名を player_type_ja で返す (旧型の object も許容)
function normalizePlayerType(
  raw: PlayerTypeInfo | string | undefined,
  ja: string | undefined,
): PlayerTypeInfo | undefined {
  if (typeof raw !== 'string') return raw
  if (raw === 'unknown') return undefined
  return { type_key: raw, type_label: ja ?? raw }
}

// 勝率を % に変換してチャートデータを作成する。
// - ラベルが無い区間はどのラリー長か読めないので描画しない
// - 件数 0 (または勝率が非有限) の区間は null: 折れ線を途切れさせ 0% として描かない
function toChartData(buckets: RallyBucket[] | undefined) {
  return (buckets ?? [])
    .filter((b) => (b.range ?? b.bucket_label ?? '') !== '')
    .map((b) => ({
      name: (b.range ?? b.bucket_label) as string,
      count: b.count,
      win_rate_pct: b.count > 0 && typeof b.win_rate === 'number' && Number.isFinite(b.win_rate)
        ? +(b.win_rate * 100).toFixed(1)
        : null,
    }))
}

export function RallyLengthWinRate({ playerId, chartHeight = 220, filters = DEFAULT_FILTERS }: RallyLengthWinRateProps) {
  const { t } = useTranslation()

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
      <div className="text-gray-500 text-sm py-8 text-center">{t('auto.RallyLengthWinRate.k1')}</div>
    )
  }

  const playerType = normalizePlayerType(resp?.data?.player_type, resp?.data?.player_type_ja)
  const sampleSize = resp?.meta?.sample_size ?? 0

  const chartData = toChartData(resp?.data?.buckets)

  if (chartData.length === 0 || sampleSize === 0) {
    return (
      <div className="text-gray-500 text-sm py-4 text-center">
        {t('auto.RallyLengthWinRate.insufficient')}
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {/* 信頼度バッジ + プレイヤータイプバッジ */}
      <div className="flex flex-wrap items-center gap-2">
        <ConfidenceBadge sampleSize={sampleSize} unit="rallies" />
        {playerType && (
          <span
            className={`inline-flex items-center px-2 py-1 rounded-ss-sm border text-xs font-medium ${playerTypeBadgeClass(
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
          <XAxis dataKey="name" tick={{ fill: 'var(--ss-t3)', fontSize: 11 }} />
          {/* 左 Y 軸: 件数 */}
          <YAxis
            yAxisId="count"
            orientation="left"
            tick={{ fill: 'var(--ss-t3)', fontSize: 11 }}
            allowDecimals={false}
          />
          {/* 右 Y 軸: 勝率 % */}
          <YAxis
            yAxisId="rate"
            orientation="right"
            domain={[0, 100]}
            tickFormatter={(v) => `${v}%`}
            tick={{ fill: 'var(--ss-t3)', fontSize: 11 }}
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
          {t('auto.RallyLengthWinRate.count_legend')}
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-3 h-0.5" style={{ backgroundColor: LINE }} />
          {t('auto.RallyLengthWinRate.rate_legend')}
        </span>
      </div>
    </div>
  )
}
