import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'
import { EvidenceBadge } from '@/components/dashboard/EvidenceBadge'
import { ResearchNotice } from '@/components/dashboard/ResearchNotice'
import { useCardTheme } from '@/hooks/useCardTheme'
import { AnalysisFilters } from '@/types'

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
  const { card, textHeading, textSecondary, textMuted, textFaint, tableHeader, rowBorder, rowHover, loading } = useCardTheme()
  const filterApiParams = {
    ...(filters.result !== 'all' ? { result: filters.result } : {}),
    ...(filters.tournamentLevel ? { tournament_level: filters.tournamentLevel } : {}),
    ...(filters.dateFrom ? { date_from: filters.dateFrom } : {}),
    ...(filters.dateTo ? { date_to: filters.dateTo } : {}),
  }
  const { data, isLoading } = useQuery({
    queryKey: ['epv-state-map', playerId, filters],
    queryFn: () => apiGet<{ success: boolean; data: StateRow[]; meta: Meta }>('/analysis/epv_state_map', { player_id: playerId, ...filterApiParams }),
  })
  const meta = data?.meta
  const reliableRows = (data?.data ?? []).filter((r) => r.reliability >= 0.5).slice(0, 12)

  return (
    <div className={`${card} rounded-lg p-4 space-y-3`}>
      <div className="flex items-center justify-between">
        <h3 className={`text-sm font-semibold ${textHeading}`}>状態ベース EPV マップ</h3>
        <EvidenceBadge tier="research" evidenceLevel="directional" sampleSize={meta?.sample_size} recommendationAllowed={false} />
      </div>
      <ResearchNotice
        caution={meta?.caution ?? 'EPVはMarkovモデルに基づく探索的指標です。定常性・独立ラリー仮定を含みます。'}
        assumptions={meta?.assumptions ?? undefined}
        promotionCriteria="状態ごとN≥50・CI幅0.2以内・クロス大会安定性"
      />
      {isLoading ? (
        <p className={`text-sm text-center py-4 ${loading}`}>計算中...</p>
      ) : reliableRows.length === 0 ? (
        <p className={`text-sm text-center py-4 ${loading}`}>十分なデータがありません（各状態で最低10ラリー以上が必要です）</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className={tableHeader}>
                <th className="text-left py-1.5 pr-3">スコアフェーズ</th>
                <th className="text-left py-1.5 pr-3">ラリー長</th>
                <th className="text-left py-1.5 pr-3">サーブ側</th>
                <th className="text-right py-1.5 pr-3">N</th>
                <th className="text-right py-1.5 pr-3">勝率</th>
                <th className="text-right py-1.5 pr-3">CI</th>
                <th className="text-left py-1.5">上位EPVショット</th>
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
      )}
      <p className={`text-[10px] ${textFaint}`}>信頼性 ≥ 50% の状態のみ表示。CI幅が広い行は解釈に注意してください。</p>
    </div>
  )
}
