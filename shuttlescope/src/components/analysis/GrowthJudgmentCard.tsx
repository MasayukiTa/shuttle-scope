// Phase 2: 成長判定カード（improving/stable/declining/pending）
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiGet } from '@/api/client'
import { NoDataMessage } from '@/components/common/NoDataMessage'
import { useIsLightMode } from '@/hooks/useIsLightMode'

interface GrowthJudgmentCardProps {
  playerId: number
  minMatches?: number
}

interface MetricResult {
  trend: 'improving' | 'stable' | 'declining' | 'pending'
  delta: number
}

interface GrowthJudgmentResponse {
  success: boolean
  data: {
    judgment: 'improving' | 'stable' | 'declining' | 'pending'
    judgment_ja: string
    metrics: Record<string, MetricResult>
    match_count: number
    annotated_match_count?: number
    min_matches_required: number
  }
}

const JUDGMENT_STYLE = {
  improving: { bg: 'rgba(59,130,246,0.12)', border: '#3b82f6', text: '#60a5fa', lightText: '#1d4ed8', icon: '↑' },
  stable:    { bg: 'rgba(107,114,128,0.12)', border: '#6b7280', text: '#9ca3af', lightText: '#4b5563', icon: '→' },
  declining: { bg: 'rgba(239,68,68,0.12)',  border: '#ef4444', text: '#f87171', lightText: '#dc2626', icon: '↓' },
  pending:   { bg: 'rgba(234,179,8,0.10)',  border: '#eab308', text: '#fbbf24', lightText: '#b45309', icon: '?' },
} as const

const METRIC_LABELS: Record<string, string> = {
  win_rate: '勝率',
  serve_win_rate: 'サーブ勝率',
  avg_rally_length: '平均ラリー長',
}

export function GrowthJudgmentCard({ playerId, minMatches = 5 }: GrowthJudgmentCardProps) {
  const { t } = useTranslation()
  const isLight = useIsLightMode()

  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-growth-judgment', playerId, minMatches],
    queryFn: () =>
      apiGet<GrowthJudgmentResponse>('/analysis/growth_judgment', {
        player_id: playerId,
        min_matches: minMatches,
      }),
    enabled: !!playerId,
  })

  if (isLoading) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.loading')}</div>
  }

  const sampleSize = resp?.meta?.sample_size ?? 0
  const data = resp?.data
  if (!data || sampleSize === 0) {
    return <NoDataMessage sampleSize={sampleSize} minRequired={minMatches} unit="試合" />
  }

  const style = JUDGMENT_STYLE[data.judgment] ?? JUDGMENT_STYLE.pending
  const textColor = isLight ? style.lightText : style.text
  const subColor = isLight ? '#475569' : '#9ca3af'
  const mutedColor = isLight ? '#64748b' : '#6b7280'

  return (
    <div className="space-y-3">
      {/* 総合判定バッジ */}
      <div
        className="flex items-center gap-3 rounded-lg px-4 py-3"
        style={{ backgroundColor: style.bg, border: `1.5px solid ${style.border}` }}
      >
        <span className="text-2xl font-bold" style={{ color: textColor }}>
          {style.icon}
        </span>
        <div>
          <p className="text-xs" style={{ color: subColor }}>{t('analysis.growth.judgment_label')}</p>
          <p className="text-base font-bold" style={{ color: textColor }}>
            {data.judgment_ja}
          </p>
        </div>
        <div className="ml-auto text-right">
          <p className="text-xs" style={{ color: mutedColor }}>
            {data.annotated_match_count ?? data.match_count}試合分析済
          </p>
          {data.judgment === 'pending' && (
            <p className="text-[10px]" style={{ color: mutedColor }}>
              {(data.annotated_match_count ?? 0) < data.min_matches_required
                ? `判定に${data.min_matches_required}試合以上のアノテーションが必要`
                : 'データ蓄積中（傾向算出に時間が必要）'}
            </p>
          )}
        </div>
      </div>

      {/* 指標別内訳 */}
      {Object.keys(data.metrics).length > 0 && (
        <div className="space-y-1.5">
          {Object.entries(data.metrics).map(([key, m]) => {
            const ms = JUDGMENT_STYLE[m.trend] ?? JUDGMENT_STYLE.pending
            const mText = isLight ? ms.lightText : ms.text
            const deltaStr = m.delta >= 0 ? `+${(m.delta * 100).toFixed(1)}%` : `${(m.delta * 100).toFixed(1)}%`
            return (
              <div
                key={key}
                className="flex items-center justify-between px-3 py-1.5 rounded"
                style={{ backgroundColor: ms.bg }}
              >
                <span className="text-xs" style={{ color: isLight ? '#1e293b' : '#d1d5db' }}>
                  {METRIC_LABELS[key] ?? key}
                </span>
                <div className="flex items-center gap-2">
                  <span className="text-xs" style={{ color: mText }}>{ms.icon}</span>
                  <span className="text-xs font-mono" style={{ color: mText }}>{deltaStr}</span>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
