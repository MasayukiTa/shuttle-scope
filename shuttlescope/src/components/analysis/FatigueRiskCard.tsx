// 疲労・崩壊リスクカード — Phase C
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { NoDataMessage } from '@/components/common/NoDataMessage'
import { RoleGuard } from '@/components/common/RoleGuard'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { LOSS } from '@/styles/colors'

interface FatigueBreakdown {
  temporal_drop: number
  long_rally_penalty: number
  pressure_drop: number
  early_sample: number
  late_sample: number
  long_rally_sample: number
  pressure_sample: number
  total_rallies: number
}

interface FatigueData {
  risk_score: number
  risk_signals: string[]
  confidence: number
  recommendation: string | null
  breakdown: FatigueBreakdown
}

interface FatigueResponse {
  success: boolean
  data: FatigueData
  meta: { confidence: { level: string; stars: string; label: string } }
}

interface FatigueRiskCardProps {
  playerId: number
  tournamentLevel?: string
}

function RiskBar({ value, label }: { value: number; label: string }) {
  const { t } = useTranslation()

  const pct = Math.min(100, Math.round(value * 100))
  const color = pct >= 12 ? LOSS : pct >= 6 ? '#f59e0b' : '#6b7280'
  return (
    <div className="space-y-0.5">
      <div className="flex justify-between text-xs" style={{ color: '#9ca3af' }}>
        <span>{label}</span>
        <span className="font-mono">{pct}%</span>
      </div>
      <div className="h-2 bg-gray-700 rounded overflow-hidden">
        <div
          className="h-full rounded transition-all"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
    </div>
  )
}

function Inner({ playerId, tournamentLevel }: FatigueRiskCardProps) {
  const { t } = useTranslation()
  const isLight = useIsLightMode()
  const subText = isLight ? '#64748b' : '#9ca3af'
  const neutral = isLight ? '#334155' : '#d1d5db'

  const { data: resp, isLoading } = useQuery({
    queryKey: ['prediction-fatigue-risk', playerId, tournamentLevel],
    queryFn: () =>
      apiGet<FatigueResponse>('/prediction/fatigue_risk', {
        player_id: playerId,
        ...(tournamentLevel ? { tournament_level: tournamentLevel } : {}),
      }),
    enabled: !!playerId,
  })

  if (isLoading) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('prediction.loading')}</div>
  }

  const d = resp?.data
  if (!d || d.breakdown.total_rallies < 10) {
    return <NoDataMessage sampleSize={d?.breakdown.total_rallies ?? 0} minRequired={30} unit="ラリー" />
  }

  const riskPct = Math.round(d.risk_score * 100)
  const riskColor = riskPct >= 12 ? LOSS : riskPct >= 6 ? '#f59e0b' : '#6b7280'

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3 flex-wrap">
        <ConfidenceBadge sampleSize={d.breakdown.total_rallies} />
        <span className="text-xs" style={{ color: subText }}>
          {d.breakdown.total_rallies}ラリー
        </span>
      </div>

      {/* リスクスコア大表示 */}
      <div className="text-center">
        <p className="text-4xl font-bold" style={{ color: riskColor }}>
          {riskPct}%
        </p>
        <p className="text-[11px] mt-1" style={{ color: subText }}>
          {t('prediction.fatigue_risk_score')}
        </p>
      </div>

      {/* シグナル */}
      {d.risk_signals.length > 0 && (
        <ul className="space-y-1">
          {d.risk_signals.map((s, i) => (
            <li key={i} className="text-xs flex gap-2" style={{ color: LOSS }}>
              <span>⚠</span>
              {s}
            </li>
          ))}
        </ul>
      )}

      {d.risk_signals.length === 0 && (
        <p className="text-xs" style={{ color: subText }}>{t('auto.FatigueRiskCard.k1')}</p>
      )}

      {/* 推奨 */}
      {d.recommendation && (
        <div className="border-t border-gray-700 pt-3">
          <p className="text-xs font-medium mb-1" style={{ color: subText }}>
            {t('prediction.recommendation')}
          </p>
          <p className="text-xs" style={{ color: neutral }}>
            {d.recommendation}
          </p>
        </div>
      )}

      {/* 内訳バー */}
      <div className="border-t border-gray-700 pt-3 space-y-2">
        <p className="text-xs font-medium" style={{ color: subText }}>
          {t('prediction.fatigue_breakdown')}
        </p>
        <RiskBar value={d.breakdown.temporal_drop} label={t('prediction.temporal_drop')} />
        <RiskBar value={d.breakdown.long_rally_penalty} label={t('prediction.long_rally_penalty')} />
        <RiskBar value={d.breakdown.pressure_drop} label={t('prediction.pressure_drop')} />
      </div>
    </div>
  )
}

export function FatigueRiskCard({ playerId, tournamentLevel }: FatigueRiskCardProps) {
  const { t } = useTranslation()

  return (
    <RoleGuard allowedRoles={['analyst', 'coach']}>
      <div className="bg-gray-800 rounded-lg p-4">
        <h3 className="text-sm font-semibold text-gray-200 mb-3">{t('auto.FatigueRiskCard.k2')}</h3>
        <Inner playerId={playerId} tournamentLevel={tournamentLevel} />
      </div>
    </RoleGuard>
  )
}
