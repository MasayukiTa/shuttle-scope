// プレッシャー下のパフォーマンスを通常時・終盤・デュース時で比較する3列カード
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { AnalysisFilters, DEFAULT_FILTERS } from '@/types'
import { perfColor, lightSafe, WIN, LOSS } from '@/styles/colors'
import { useIsLightMode } from '@/hooks/useIsLightMode'

interface PressurePerformanceProps {
  playerId: number
  filters?: AnalysisFilters
}

interface PressureSegment {
  label: string          // "通常時" / "終盤（17点以降）" / "デュース時"
  win_rate: number
  rally_count: number
  sample_size: number
}

interface PressureResponse {
  data: {
    normal: PressureSegment
    endgame: PressureSegment
    deuce: PressureSegment
  }
  meta: {
    sample_size: number
    confidence: { level: string; stars: string; label: string; warning?: string }
  }
}

function pctStr(v: number): string {
  return `${(v * 100).toFixed(1)}%`
}

// 単一の圧力セグメントカード
function SegmentCard({
  segment,
  highlight,
  isLight,
}: {
  segment: PressureSegment
  highlight?: boolean
  isLight: boolean
}) {
  const barWidth = `${Math.min(segment.win_rate * 100, 100).toFixed(1)}%`
  const color = lightSafe(perfColor(segment.win_rate), !isLight)
  return (
    <div
      className={`rounded-lg p-4 flex flex-col gap-2 ${
        highlight ? 'bg-gray-700/60 border border-gray-600' : 'bg-gray-700/30'
      }`}
    >
      <p className="text-xs text-gray-400 font-medium">{segment.label}</p>
      <p className="text-2xl font-bold" style={{ color }}>
        {pctStr(segment.win_rate)}
      </p>
      {/* 進捗バー */}
      <div className="w-full bg-gray-600 rounded-full h-1.5">
        <div
          className="h-1.5 rounded-full transition-all"
          style={{ width: barWidth, backgroundColor: color }}
        />
      </div>
      <p className="text-xs text-gray-500">
        ラリー数: <span className="text-gray-300">{segment.rally_count}</span>
      </p>
    </div>
  )
}

export function PressurePerformance({ playerId, filters = DEFAULT_FILTERS }: PressurePerformanceProps) {
  const isLight = useIsLightMode()
  const fp = {
    ...(filters.result !== 'all' ? { result: filters.result } : {}),
    ...(filters.tournamentLevel ? { tournament_level: filters.tournamentLevel } : {}),
    ...(filters.dateFrom ? { date_from: filters.dateFrom } : {}),
    ...(filters.dateTo ? { date_to: filters.dateTo } : {}),
  }
  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-pressure-performance', playerId, filters],
    queryFn: () =>
      apiGet<PressureResponse>('/analysis/pressure_performance', {
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

  const sampleSize = resp?.meta?.sample_size ?? 0

  if (!resp?.data || sampleSize === 0) {
    return (
      <div className="text-gray-500 text-sm py-4 text-center">
        データ不足（アノテーション後に解析可能）
      </div>
    )
  }

  const { normal, endgame, deuce } = resp.data

  // 通常時と比べた終盤・デュース時の変化を矢印で表示
  function DeltaBadge({ base, target }: { base: number; target: number }) {
    const delta = target - base
    const absPct = Math.abs(delta * 100).toFixed(1)
    if (Math.abs(delta) < 0.005) {
      return <span className="text-xs text-gray-500">±0.0%</span>
    }
    return delta > 0 ? (
      <span className="text-xs font-semibold" style={{ color: lightSafe(WIN, !isLight) }}>+{absPct}%</span>
    ) : (
      <span className="text-xs font-semibold" style={{ color: lightSafe(LOSS, !isLight) }}>−{absPct}%</span>
    )
  }

  return (
    <div className="space-y-3">
      {/* 信頼度バッジ */}
      <ConfidenceBadge sampleSize={sampleSize} />

      {/* 3列カード */}
      <div className="grid grid-cols-3 gap-3">
        <SegmentCard segment={normal} isLight={isLight} />
        <SegmentCard segment={endgame} highlight isLight={isLight} />
        <SegmentCard segment={deuce} highlight isLight={isLight} />
      </div>

      {/* 通常時からの変化 */}
      <div className="flex gap-3 text-xs">
        <div className="flex-1" />
        <div className="flex-1 flex items-center justify-center gap-1 text-gray-400">
          通常比 <DeltaBadge base={normal.win_rate} target={endgame.win_rate} />
        </div>
        <div className="flex-1 flex items-center justify-center gap-1 text-gray-400">
          通常比 <DeltaBadge base={normal.win_rate} target={deuce.win_rate} />
        </div>
      </div>
    </div>
  )
}
