// Phase 3: 相手タイプ別相性（攻撃型/守備型/バランス型）
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { NoDataMessage } from '@/components/common/NoDataMessage'
import { AnalysisFilters, DEFAULT_FILTERS } from '@/types'
import { WIN, LOSS } from '@/styles/colors'
import { useIsLightMode } from '@/hooks/useIsLightMode'

interface OpponentTypeAffinityProps {
  playerId: number
  filters?: AnalysisFilters
}

interface AffinityEntry {
  win_rate: number
  match_count: number
  wins: number
}

interface SummaryEntry {
  opponent_type: string
  win_rate: number
  match_count: number
}

interface OpponentTypeAffinityResponse {
  success: boolean
  data: {
    affinity: Record<string, AffinityEntry>
    summary: SummaryEntry[]
  }
  meta: { sample_size: number; confidence: { level: string; stars: string; label: string } }
}

// タイプ別アイコン
const TYPE_ICON: Record<string, string> = {
  攻撃型: '⚡',
  守備型: '🛡',
  バランス型: '⚖',
}

export function OpponentTypeAffinity({ playerId, filters = DEFAULT_FILTERS }: OpponentTypeAffinityProps) {
  const { t } = useTranslation()
  const isLight = useIsLightMode()

  const fp = {
    player_id: playerId,
    ...(filters.result !== 'all' ? { result: filters.result } : {}),
    ...(filters.tournamentLevel ? { tournament_level: filters.tournamentLevel } : {}),
    ...(filters.dateFrom ? { date_from: filters.dateFrom } : {}),
    ...(filters.dateTo ? { date_to: filters.dateTo } : {}),
  }

  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-opponent-type-affinity', playerId, filters],
    queryFn: () => apiGet<OpponentTypeAffinityResponse>('/analysis/opponent_type_affinity', fp),
    enabled: !!playerId,
  })

  if (isLoading) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.loading')}</div>
  }

  const sampleSize = resp?.meta?.sample_size ?? 0
  const summary = resp?.data?.summary ?? []

  if (sampleSize === 0 || summary.length === 0) {
    return <NoDataMessage sampleSize={sampleSize} minRequired={3} unit="試合" />
  }

  const labelColor = isLight ? '#475569' : '#9ca3af'
  const rowBg     = isLight ? '#f8fafc' : '#1f2937'
  const rowBorder = isLight ? '#e2e8f0' : '#374151'
  const textMain  = isLight ? '#1e293b' : '#e2e8f0'

  return (
    <div className="space-y-3">
      <ConfidenceBadge sampleSize={sampleSize} />

      <div className="space-y-2">
        {summary.map((entry) => {
          const wr = entry.win_rate
          const barColor = wr >= 0.5 ? WIN : LOSS
          const wrText = wr >= 0.5 ? WIN : LOSS
          const icon = TYPE_ICON[entry.opponent_type] ?? '?'

          return (
            <div
              key={entry.opponent_type}
              className="rounded-lg p-3"
              style={{ backgroundColor: rowBg, border: `1px solid ${rowBorder}` }}
            >
              <div className="flex items-center justify-between mb-1.5">
                <div className="flex items-center gap-1.5">
                  <span className="text-sm">{icon}</span>
                  <span className="text-sm font-semibold" style={{ color: textMain }}>
                    {entry.opponent_type}
                  </span>
                </div>
                <div className="text-right">
                  <span className="text-base font-bold" style={{ color: wrText }}>
                    {(wr * 100).toFixed(0)}%
                  </span>
                  <span className="text-xs ml-1.5" style={{ color: labelColor }}>
                    {entry.wins ?? 0}勝{entry.match_count - (entry.wins ?? 0)}敗
                  </span>
                </div>
              </div>

              {/* 勝率バー */}
              <div
                className="w-full rounded-full h-1.5 overflow-hidden"
                style={{ backgroundColor: isLight ? '#e2e8f0' : '#374151' }}
              >
                <div
                  className="h-1.5 rounded-full transition-all"
                  style={{ width: `${(wr * 100).toFixed(0)}%`, backgroundColor: barColor }}
                />
              </div>
            </div>
          )
        })}
      </div>

      <p className="text-[10px]" style={{ color: labelColor }}>
        ※ 相手タイプはラリー長・スマッシュ率から自動判定
      </p>
    </div>
  )
}
