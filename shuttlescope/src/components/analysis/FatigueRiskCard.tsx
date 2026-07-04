// 疲労・崩壊リスクカード — Phase C
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { NoDataMessage } from '@/components/common/NoDataMessage'
import { RoleGuard } from '@/components/common/RoleGuard'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { LOSS } from '@/styles/colors'
import { MIcon } from '@/components/common/MIcon'

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

  const pct = Math.min(100, Math.round(value * 100))
  const color = pct >= 12 ? LOSS : pct >= 6 ? 'var(--ss-warn)' : 'var(--ss-border)'
  return (
    <div className="space-y-0.5">
      <div className="flex justify-between text-xs text-[var(--ss-t3)]">
        <span>{label}</span>
        <span className="ss-num font-mono">{pct}%</span>
      </div>
      <div className="h-2 bg-[var(--ss-surface-3)] rounded-ss-full overflow-hidden">
        <div
          className="h-full rounded-ss-full transition-all duration-base ease-out"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
    </div>
  )
}

function Inner({ playerId, tournamentLevel }: FatigueRiskCardProps) {
  const { t } = useTranslation()
  const isLight = useIsLightMode()

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
    return <div className="text-[var(--ss-t3)] text-sm py-4 text-center">{t('prediction.loading')}</div>
  }

  const d = resp?.data
  if (!d || d.breakdown.total_rallies < 10) {
    return <NoDataMessage sampleSize={d?.breakdown.total_rallies ?? 0} minRequired={30} unit="ラリー" />
  }

  const riskPct = Math.round(d.risk_score * 100)
  const riskColor = riskPct >= 12 ? LOSS : riskPct >= 6 ? 'var(--ss-warn)' : 'var(--ss-border)'

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3 flex-wrap">
        <ConfidenceBadge sampleSize={d.breakdown.total_rallies} />
        <span className="text-xs text-[var(--ss-t3)]">
          {t('auto._shared.n_rallies', { n: d.breakdown.total_rallies })}
        </span>
      </div>

      {/* リスクスコア大表示 */}
      <div className="text-center">
        <p className="ss-num text-4xl font-bold" style={{ color: riskColor }}>
          {riskPct}%
        </p>
        <p className="text-[11px] mt-1 text-[var(--ss-t3)]">
          {t('prediction.fatigue_risk_score')}
        </p>
      </div>

      {/* シグナル */}
      {d.risk_signals.length > 0 && (
        <ul className="space-y-1">
          {d.risk_signals.map((s, i) => (
            <li key={i} className="text-xs flex gap-2" style={{ color: LOSS }}>
              <MIcon name="warning" size={14} />
              {s}
            </li>
          ))}
        </ul>
      )}

      {d.risk_signals.length === 0 && (
        <p className="text-xs text-[var(--ss-t3)]">{t('auto.FatigueRiskCard.k1')}</p>
      )}

      {/* 推奨 */}
      {d.recommendation && (
        <div className="border-t border-[var(--ss-border)] pt-3">
          <p className="text-xs font-medium mb-1 text-[var(--ss-t3)]">
            {t('prediction.recommendation')}
          </p>
          <p className="text-xs text-[var(--ss-t2)]">
            {d.recommendation}
          </p>
        </div>
      )}

      {/* 内訳バー */}
      <div className="border-t border-[var(--ss-border)] pt-3 space-y-2">
        <p className="text-xs font-medium text-[var(--ss-t3)]">
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
      <div className="bg-[var(--ss-surface-1)] rounded-ss-lg border border-[var(--ss-border)] p-4">
        <h3 className="text-sm font-semibold text-[var(--ss-t1)] mb-3">{t('auto.FatigueRiskCard.k2')}</h3>
        <Inner playerId={playerId} tournamentLevel={tournamentLevel} />
      </div>
    </RoleGuard>
  )
}
