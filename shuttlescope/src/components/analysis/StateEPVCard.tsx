import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'
import { useResearchBundleSlice } from '@/contexts/ResearchBundleContext'
import { EvidenceBadge } from '@/components/dashboard/EvidenceBadge'
import { ResearchNotice } from '@/components/dashboard/ResearchNotice'
import { useCardTheme } from '@/hooks/useCardTheme'
import { AnalysisFilters } from '@/types'
import { useTranslation } from 'react-i18next'

interface StateRow {
  state_key: string
  state: { score_phase: string; set_phase: string; rally_bucket: string; player_role: string }
  n: number
  win_rate: number
  ci_low: number
  ci_high: number
  reliability: number
  top_epv_shots: { shot_type: string; epv: number }[]
}
interface Meta { tier: string; evidence_level: string; sample_size: number; caution: string | null; assumptions: string | null }
interface Props { playerId: number; filters: AnalysisFilters }

const SCORE_PHASE_LABELS: Record<string, string> = { early: '序盤', mid: '中盤', deuce: 'デュース', endgame: '終盤' }
const RALLY_BUCKET_LABELS: Record<string, string> = { short: '短(〜4)', medium: '中(5-9)', long: '長(10+)' }
const ROLE_LABELS: Record<string, string> = { server: 'サーバー', receiver: 'レシーバー' }
function pct(v: number) { return `${(v * 100).toFixed(1)}%` }

export function StateEPVCard({ playerId, filters }: Props) {
  const { t } = useTranslation()

  const { card, textHeading, textSecondary, textMuted, textFaint, tableHeader, rowBorder, rowHover, loading } = useCardTheme()
  const filterApiParams = {
    ...(filters.result !== 'all' ? { result: filters.result } : {}),
    ...(filters.tournamentLevel ? { tournament_level: filters.tournamentLevel } : {}),
    ...(filters.dateFrom ? { date_from: filters.dateFrom } : {}),
    ...(filters.dateTo ? { date_to: filters.dateTo } : {}),
  }
  // bundle 提供時はスライスを使い、個別リクエストはスキップする
  type Resp = { success: boolean; data: StateRow[]; meta: Meta }
  const { slice: bundled, loading: bundleLoading, provided } = useResearchBundleSlice<Resp>('epv_state_table')
  const indiv = useQuery({
    queryKey: ['epv-state-map', playerId, filters],
    queryFn: () => apiGet<Resp>('/analysis/epv_state_map', { player_id: playerId, ...filterApiParams }),
    enabled: !!playerId && !provided && !bundleLoading,
  })
  const data = bundled ?? indiv.data
  const isLoading = provided ? bundleLoading : indiv.isLoading
  const meta = data?.meta
  // バンドル経由は data.data が dict 形式の場合があるため Array.isArray でガード
  const rawRows = Array.isArray(data?.data) ? data.data : []
  const reliableRows = rawRows.filter((r) => r.reliability >= 0.5).slice(0, 12)

  return (
    <div className={`${card} rounded-lg p-4 space-y-3`}>
      <div className="flex items-center justify-between">
        <h3 className={`text-sm font-semibold ${textHeading}`}>{t('auto.StateEPVCard.k1')}</h3>
        <EvidenceBadge tier="research" evidenceLevel="directional" sampleSize={meta?.sample_size} recommendationAllowed={false} />
      </div>
      <ResearchNotice
        caution={meta?.caution ?? 'EPVはMarkovモデルに基づく探索的指標です。定常性・独立ラリー仮定を含みます。'}
        assumptions={meta?.assumptions ?? undefined}
        promotionCriteria="状態ごとN≥50・CI幅0.2以内・クロス大会安定性"
      />
      {isLoading ? (
        <p className={`text-sm text-center py-4 ${loading}`}>{t('auto.StateEPVCard.k2')}</p>
      ) : reliableRows.length === 0 ? (
        <p className={`text-sm text-center py-4 ${loading}`}>{t('auto.StateEPVCard.k3')}</p>
      ) : (
        <>
          {/* ── モバイル: カード形式 ──────────────────────── */}
          <div className="md:hidden space-y-2">
            {reliableRows.map((row) => (
              <div key={row.state_key} className={`border rounded-xl p-3 text-xs ${rowBorder}`}>
                {/* コンテキストバッジ群 */}
                <div className="flex flex-wrap gap-1 mb-2">
                  <span className="px-1.5 py-0.5 rounded-full bg-blue-500/15 text-blue-400 text-[10px]">
                    {SCORE_PHASE_LABELS[row.state.score_phase] ?? row.state.score_phase}
                  </span>
                  <span className={`px-1.5 py-0.5 rounded-full text-[10px] ${textFaint}`}
                    style={{ background: 'rgba(107,114,128,0.15)' }}>
                    {RALLY_BUCKET_LABELS[row.state.rally_bucket] ?? row.state.rally_bucket}
                  </span>
                  <span className={`px-1.5 py-0.5 rounded-full text-[10px] ${
                    row.state.player_role === 'server' ? 'bg-green-500/15 text-green-400' : 'bg-orange-500/15 text-orange-400'
                  }`}>
                    {ROLE_LABELS[row.state.player_role] ?? row.state.player_role}
                  </span>
                </div>
                {/* 主要数値 */}
                <div className="flex items-baseline gap-3 mb-1.5">
                  <span className={`text-xl font-bold ${row.win_rate >= 0.5 ? 'text-blue-500' : 'text-red-500'}`}>
                    {pct(row.win_rate)}
                  </span>
                  <span className={`text-[10px] ${textFaint}`}>
                    [{pct(row.ci_low)}–{pct(row.ci_high)}]
                  </span>
                  <span className={`text-[10px] ${textFaint} ml-auto`}>N={row.n}</span>
                </div>
                {/* 推奨ショット */}
                {row.top_epv_shots.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {row.top_epv_shots.slice(0, 2).map((s) => (
                      <span key={s.shot_type}
                        className={`text-[10px] px-2 py-0.5 rounded ${s.epv > 0 ? 'bg-emerald-500/15 text-emerald-400' : 'bg-orange-500/15 text-orange-400'}`}>
                        {s.shot_type} ({s.epv > 0 ? '+' : ''}{(s.epv * 100).toFixed(1)}pp)
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* ── デスクトップ: テーブル ────────────────────── */}
          <div className="hidden md:block overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className={tableHeader}>
                  <th className="text-left py-1.5 pr-3">{t('auto.StateEPVCard.k4')}</th>
                  <th className="text-left py-1.5 pr-3">{t('auto.StateEPVCard.k5')}</th>
                  <th className="text-left py-1.5 pr-3">{t('auto.StateEPVCard.k6')}</th>
                  <th className="text-right py-1.5 pr-3">N</th>
                  <th className="text-right py-1.5 pr-3">{t('auto.StateEPVCard.k7')}</th>
                  <th className="text-right py-1.5 pr-3">CI</th>
                  <th className="text-left py-1.5">{t('auto.StateEPVCard.k8')}</th>
                </tr>
              </thead>
              <tbody>
                {reliableRows.map((row) => (
                  <tr key={row.state_key} className={`${rowBorder} ${rowHover}`}>
                    <td className={`py-1.5 pr-3 ${textSecondary}`}>{SCORE_PHASE_LABELS[row.state.score_phase] ?? row.state.score_phase}</td>
                    <td className={`py-1.5 pr-3 ${textSecondary}`}>{RALLY_BUCKET_LABELS[row.state.rally_bucket] ?? row.state.rally_bucket}</td>
                    <td className={`py-1.5 pr-3 ${textMuted}`}>{ROLE_LABELS[row.state.player_role] ?? row.state.player_role}</td>
                    <td className={`py-1.5 pr-3 text-right ${textMuted}`}>{row.n}</td>
                    <td className="py-1.5 pr-3 text-right">
                      <span className={row.win_rate >= 0.5 ? 'text-blue-500' : 'text-red-500'}>
                        {pct(row.win_rate)}
                      </span>
                    </td>
                    <td className={`py-1.5 pr-3 text-right text-[10px] ${textFaint}`}>[{pct(row.ci_low)}–{pct(row.ci_high)}]</td>
                    <td className={`py-1.5 ${textMuted}`}>
                      {row.top_epv_shots.slice(0, 2).map((s) => (
                        <span key={s.shot_type} className={`mr-1 text-[10px] ${s.epv > 0 ? 'text-emerald-500' : 'text-orange-500'}`}>
                          {s.shot_type}({s.epv > 0 ? '+' : ''}{(s.epv * 100).toFixed(1)}pp)
                        </span>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      <p className={`text-[10px] ${textFaint}`}>{t('auto.StateEPVCard.k9')}</p>
    </div>
  )
}
