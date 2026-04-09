import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'
import { EvidenceBadge } from '@/components/dashboard/EvidenceBadge'
import { ResearchNotice } from '@/components/dashboard/ResearchNotice'
import { useCardTheme } from '@/hooks/useCardTheme'
import { AnalysisFilters } from '@/types'

interface HazardData {
  hazard_next_loss: number
  hazard_after_long: number
  hazard_endgame: number
  combined_hazard: number
  collapse_risk_band: string
  calibrated_confidence: number
  baseline_loss_rate: number
  total_rallies: number
  after_long_rally: { n_long_rallies: number; n_loss_after_long: number; loss_rate: number; vs_baseline: number }
  endgame_analysis: { n_endgame: number; n_loss_endgame: number; loss_rate: number; vs_baseline: number }
  window_trend: { window_start: number; window_end: number; hazard: number; band: string }[]
}
interface Meta { tier: string; evidence_level: string; sample_size: number; caution: string | null }
interface Props { playerId: number; filters: AnalysisFilters }

const BAND_COLORS: Record<string, string> = {
  low: 'text-emerald-500', moderate: 'text-yellow-500', high: 'text-orange-500', critical: 'text-red-500',
}
const BAND_LABELS: Record<string, string> = {
  low: '低リスク', moderate: '中程度', high: '高リスク', critical: '危険',
}
function pct(v: number) { return `${(v * 100).toFixed(1)}%` }

export function HazardFatigueCard({ playerId, filters }: Props) {
  const { card, cardInner, cardInnerAlt, textHeading, textSecondary, textMuted, textFaint, loading } = useCardTheme()
  const filterApiParams = {
    ...(filters.result !== 'all' ? { result: filters.result } : {}),
    ...(filters.tournamentLevel ? { tournament_level: filters.tournamentLevel } : {}),
    ...(filters.dateFrom ? { date_from: filters.dateFrom } : {}),
    ...(filters.dateTo ? { date_to: filters.dateTo } : {}),
  }
  const { data, isLoading } = useQuery({
    queryKey: ['hazard-fatigue', playerId, filters],
    queryFn: () => apiGet<{ success: boolean; data: HazardData; meta: Meta }>('/analysis/hazard_fatigue', { player_id: playerId, ...filterApiParams }),
  })
  const meta = data?.meta
  const d = data?.data

  return (
    <div className={`${card} rounded-lg p-4 space-y-3`}>
      <div className="flex items-center justify-between">
        <h3 className={`text-sm font-semibold ${textHeading}`}>ハザード・疲労モデル</h3>
        <EvidenceBadge tier="research" evidenceLevel="exploratory" sampleSize={meta?.sample_size} recommendationAllowed={false} />
      </div>
      <ResearchNotice
        caution={meta?.caution ?? 'ハザード推定はラリー結果パターンから計算します。実際の疲労とは異なる場合があります。'}
        assumptions="離散時間ハザードモデル（Cox比例ハザードの簡略版）。実際の体力測定は使用しません。"
        promotionCriteria="生理指標との相関確認・N≥500ラリーの安定確認"
      />
      {isLoading ? (
        <p className={`text-sm text-center py-4 ${loading}`}>計算中...</p>
      ) : !d || d.total_rallies === 0 ? (
        <p className={`text-sm text-center py-4 ${loading}`}>データなし</p>
      ) : (
        <div className="space-y-3">
          <div className={`flex items-center gap-4 ${cardInner} rounded px-3 py-2`}>
            <div>
              <p className={`text-[10px] ${textMuted}`}>総合崩壊リスク</p>
              <p className={`text-lg font-bold ${BAND_COLORS[d.collapse_risk_band] ?? textSecondary}`}>
                {BAND_LABELS[d.collapse_risk_band] ?? d.collapse_risk_band}
              </p>
              <p className={`text-[10px] ${textMuted}`}>信頼度: {pct(d.calibrated_confidence)} (N={d.total_rallies})</p>
            </div>
            <div className="ml-auto text-right">
              <p className={`text-[10px] ${textMuted}`}>ベースライン失点率</p>
              <p className={`text-sm ${textSecondary}`}>{pct(d.baseline_loss_rate)}</p>
            </div>
          </div>
          <div className="grid grid-cols-3 gap-2">
            {[
              { label: '直近ウィンドウ', value: d.hazard_next_loss },
              { label: 'ロングラリー後', value: d.hazard_after_long },
              { label: '終盤(18+)', value: d.hazard_endgame },
            ].map(({ label, value }) => (
              <div key={label} className={`${cardInnerAlt} rounded px-2 py-2 text-center`}>
                <p className={`text-[10px] mb-1 ${textMuted}`}>{label}</p>
                <p className={`text-sm font-semibold ${value >= 0.5 ? 'text-red-500' : value >= 0.4 ? 'text-yellow-500' : 'text-emerald-500'}`}>
                  {pct(value)}
                </p>
              </div>
            ))}
          </div>
          <div className={`text-[11px] space-y-0.5 ${textSecondary}`}>
            <p>
              ロングラリー後 (8+打): {d.after_long_rally.n_long_rallies}件中 {d.after_long_rally.n_loss_after_long}失点
              <span className={`ml-1 ${d.after_long_rally.vs_baseline > 0.05 ? 'text-orange-500' : textFaint}`}>
                (ベースライン比 {d.after_long_rally.vs_baseline > 0 ? '+' : ''}{pct(d.after_long_rally.vs_baseline)})
              </span>
            </p>
            <p>
              終盤局面: {d.endgame_analysis.n_endgame}件中 {d.endgame_analysis.n_loss_endgame}失点
              <span className={`ml-1 ${d.endgame_analysis.vs_baseline > 0.05 ? 'text-orange-500' : textFaint}`}>
                (ベースライン比 {d.endgame_analysis.vs_baseline > 0 ? '+' : ''}{pct(d.endgame_analysis.vs_baseline)})
              </span>
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
