import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'
import { EvidenceBadge } from '@/components/dashboard/EvidenceBadge'
import { ResearchNotice } from '@/components/dashboard/ResearchNotice'
import { useCardTheme } from '@/hooks/useCardTheme'
import { AnalysisFilters } from '@/types'

interface ShotTypeStat {
  avg: number
  ci_low: number
  ci_high: number
  n: number
}

interface TopShot {
  shot_type: string
  avg_influence: number
  ci_low: number
  ci_high: number
  n: number
}

interface StateBreakdownEntry {
  state_key: string
  state_epv: number
  avg_influence: number
  ci_low: number
  ci_high: number
  n_rallies: number
  top_shots: TopShot[]
}

interface ShotInfluenceV2Data {
  per_shot_type: Record<string, ShotTypeStat>
  state_breakdown: StateBreakdownEntry[]
  total_rallies: number
  usable_rallies: number
}

interface Meta {
  tier: string
  evidence_level: string
  sample_size: number
  caution: string | null
}

interface Props {
  playerId: number
  filters: AnalysisFilters
}

function InfluenceBar({ value, max = 1, isLight }: { value: number; max?: number; isLight: boolean }) {
  const ratio = Math.min(value / max, 1)
  return (
    <div className="flex items-center gap-1.5">
      <div className={`w-20 h-1.5 rounded-full overflow-hidden ${isLight ? 'bg-gray-200' : 'bg-gray-700'}`}>
        <div
          className="h-full rounded-full bg-indigo-500"
          style={{ width: `${ratio * 100}%` }}
        />
      </div>
      <span className={`text-[10px] tabular-nums ${isLight ? 'text-gray-500' : 'text-gray-500'}`}>{value.toFixed(3)}</span>
    </div>
  )
}

export function ShotInfluenceV2Card({ playerId, filters }: Props) {
  const { card, cardInnerAlt, textHeading, textSecondary, textMuted, textFaint, loading, isLight } = useCardTheme()
  const filterApiParams = {
    ...(filters.result !== 'all' ? { result: filters.result } : {}),
    ...(filters.tournamentLevel ? { tournament_level: filters.tournamentLevel } : {}),
    ...(filters.dateFrom ? { date_from: filters.dateFrom } : {}),
    ...(filters.dateTo ? { date_to: filters.dateTo } : {}),
  }

  const { data, isLoading } = useQuery({
    queryKey: ['shot-influence-v2', playerId, filters],
    queryFn: () =>
      apiGet<{ success: boolean; data: ShotInfluenceV2Data; meta: Meta }>(
        '/analysis/shot_influence_v2',
        { player_id: playerId, ...filterApiParams }
      ),
  })

  const meta = data?.meta
  const influenceData = data?.data
  const perShotType = influenceData?.per_shot_type ?? {}
  const topShots = Object.entries(perShotType)
    .sort((a, b) => b[1].avg - a[1].avg)
    .slice(0, 10)
  const maxInfluence = topShots.length > 0 ? topShots[0][1].avg : 1
  const stateBreakdown = (influenceData?.state_breakdown ?? []).slice(0, 6)

  return (
    <div className={`${card} rounded-lg p-4 space-y-3`}>
      <div className="flex items-center justify-between">
        <h3 className={`text-sm font-semibold ${textHeading}`}>ショット影響度 v2（状態条件付き）</h3>
        <EvidenceBadge
          tier="research"
          evidenceLevel="exploratory"
          sampleSize={meta?.sample_size}
          recommendationAllowed={false}
        />
      </div>

      <ResearchNotice
        caution={meta?.caution ?? 'ショット影響度v2は状態EPVを使ったクレジット帰属です。因果効果ではなく相関ベースです。'}
        assumptions="状態EPVを基準とし、各打のアウトカム差分をポジション・攻撃力・品質で重み付けして帰属。"
        promotionCriteria="状態ごとN≥30ラリー・BootstrapCIの追加・コーチ有用性テスト"
      />

      {isLoading ? (
        <p className={`text-sm text-center py-4 ${loading}`}>計算中...</p>
      ) : topShots.length === 0 ? (
        <p className={`text-sm text-center py-4 ${loading}`}>データが不足しています</p>
      ) : (
        <div className="space-y-3">
          <div className={`flex items-center justify-between text-[10px] ${textMuted}`}>
            <span>総ラリー: {influenceData?.total_rallies ?? 0}</span>
            <span>有効: {influenceData?.usable_rallies ?? 0}</span>
          </div>

          {/* ショット種別ランキング */}
          <div>
            <p className={`text-[10px] ${textMuted} mb-1.5`}>ショット種別平均影響度（状態補正後）</p>
            <div className="space-y-1">
              {topShots.map(([shotType, stat], i) => (
                <div key={shotType} className="flex items-center gap-2">
                  <span className={`text-[10px] w-4 text-right ${textFaint}`}>{i + 1}</span>
                  <span className={`text-xs w-24 truncate ${textSecondary}`}>{shotType}</span>
                  <InfluenceBar value={stat.avg} max={maxInfluence} isLight={isLight} />
                  <span className={`text-[10px] shrink-0 ${textFaint}`}>
                    [{stat.ci_low.toFixed(3)}–{stat.ci_high.toFixed(3)}]
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* 状態別内訳 */}
          {stateBreakdown.length > 0 && (
            <div>
              <p className={`text-[10px] ${textMuted} mb-1.5`}>状態別トップショット</p>
              <div className="space-y-2">
                {stateBreakdown.map((sb) => (
                  <div key={sb.state_key} className={`${cardInnerAlt} rounded px-2 py-1.5`}>
                    <div className="flex items-center justify-between mb-1">
                      <span className={`text-[10px] font-mono ${textSecondary}`}>{sb.state_key}</span>
                      <span className={`text-[10px] ${textFaint}`}>
                        EPV={`${(sb.state_epv * 100).toFixed(1)}%`} N={sb.n_rallies}
                      </span>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {sb.top_shots.slice(0, 3).map((ts) => (
                        <span key={ts.shot_type} className="text-[10px]">
                          <span className={textSecondary}>{ts.shot_type}</span>
                          <span className={`ml-0.5 ${textFaint}`}>({ts.avg_influence.toFixed(3)})</span>
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          <p className={`text-[10px] ${textFaint}`}>
            影響度 = 状態EPV補正後のショット寄与スコア。スコアが大きいほど勝利への貢献度が高い（相関ベース）。
          </p>
        </div>
      )}
    </div>
  )
}
