// EPVカードコンポーネント（マルコフ連鎖に基づく期待パターン価値）
// 上位パターン: 全ロール表示 / 下位パターン: アナリスト・コーチのみ
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { RoleGuard } from '@/components/common/RoleGuard'
import { AnalysisFilters, DEFAULT_FILTERS } from '@/types'
import { WIN, LOSS } from '@/styles/colors'

interface MarkovEPVProps {
  playerId: number
  filters?: AnalysisFilters
}

interface EPVPattern {
  pattern: string
  shots: string[]
  epv: number
  ci_low: number
  ci_high: number
  count: number
}

interface EPVResponse {
  success: boolean
  data: {
    top_patterns: EPVPattern[]
    bottom_patterns: EPVPattern[]
  }
  meta: { sample_size: number; confidence: { level: string; stars: string; label: string } }
}

function EPVCard({ pattern, isPositive, rank }: { pattern: EPVPattern; isPositive: boolean; rank: number }) {
  const accentColor = isPositive ? WIN : LOSS
  const epvSign = pattern.epv >= 0 ? '+' : ''
  const barWidth = Math.min(Math.abs(pattern.epv) * 400, 100)

  return (
    <div className="rounded-lg p-3 bg-gray-750 border border-gray-700 border-l-4" style={{ borderLeftColor: accentColor }}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[10px] text-gray-600 font-mono w-4 shrink-0">#{rank}</span>
            <p className="text-sm text-gray-100 font-medium leading-tight">{pattern.pattern}</p>
          </div>
          {/* EPVバー */}
          <div className="flex items-center gap-2 mt-1.5">
            <div className="flex-1 bg-gray-700 rounded-full h-1.5">
              <div
                className="h-1.5 rounded-full"
                style={{ width: `${barWidth}%`, backgroundColor: accentColor }}
              />
            </div>
            <span className="text-[10px] text-gray-500 shrink-0">{pattern.count}回</span>
          </div>
        </div>
        <div className="text-right shrink-0">
          <p className="text-xl font-bold tabular-nums" style={{ color: accentColor }}>
            {epvSign}{(pattern.epv * 100).toFixed(1)}
          </p>
          <p className="text-[10px] text-gray-600 tabular-nums">
            [{(pattern.ci_low * 100).toFixed(1)}, {(pattern.ci_high * 100).toFixed(1)}]
          </p>
        </div>
      </div>
    </div>
  )
}

export function MarkovEPV({ playerId, filters = DEFAULT_FILTERS }: MarkovEPVProps) {
  const { t } = useTranslation()

  const fp = {
    ...(filters.result !== 'all' ? { result: filters.result } : {}),
    ...(filters.tournamentLevel ? { tournament_level: filters.tournamentLevel } : {}),
    ...(filters.dateFrom ? { date_from: filters.dateFrom } : {}),
    ...(filters.dateTo ? { date_to: filters.dateTo } : {}),
  }
  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-epv', playerId, filters],
    queryFn: () =>
      apiGet<EPVResponse>('/analysis/epv', { player_id: playerId, ...fp }),
    enabled: !!playerId,
  })

  if (isLoading) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.loading')}</div>
  }

  const sampleSize = resp?.meta?.sample_size ?? 0
  const topPatterns = resp?.data?.top_patterns ?? []
  const bottomPatterns = resp?.data?.bottom_patterns ?? []

  if (sampleSize === 0 && topPatterns.length === 0) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.no_data')}</div>
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <ConfidenceBadge sampleSize={sampleSize} />
        <span className="text-[11px] text-gray-500">
          EPV = ベースライン勝率との差分（±100基準）
        </span>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
        {/* 上位パターン（全ロール） */}
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wider mb-2.5 flex items-center gap-1.5" style={{ color: WIN }}>
            <span className="inline-block w-2 h-2 rounded-full" style={{ backgroundColor: WIN }} />
            {t('analysis.epv.top_patterns')}（有効パターン）
          </h3>
          {topPatterns.length === 0 ? (
            <p className="text-gray-500 text-xs">{t('analysis.no_data')}</p>
          ) : (
            <div className="space-y-2">
              {topPatterns.slice(0, 5).map((p, i) => (
                <EPVCard key={i} pattern={p} isPositive={true} rank={i + 1} />
              ))}
            </div>
          )}
        </div>

        {/* 下位パターン（アナリスト・コーチのみ） */}
        <RoleGuard allowedRoles={['analyst', 'coach']} fallback={null}>
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wider mb-2.5 flex items-center gap-1.5" style={{ color: LOSS }}>
              <span className="inline-block w-2 h-2 rounded-full" style={{ backgroundColor: LOSS }} />
              {t('analysis.epv.bottom_patterns')}（要改善パターン）
            </h3>
            {bottomPatterns.length === 0 ? (
              <p className="text-gray-500 text-xs">{t('analysis.no_data')}</p>
            ) : (
              <div className="space-y-2">
                {bottomPatterns.slice(0, 5).map((p, i) => (
                  <EPVCard key={i} pattern={p} isPositive={false} rank={i + 1} />
                ))}
              </div>
            )}
          </div>
        </RoleGuard>
      </div>
    </div>
  )
}
