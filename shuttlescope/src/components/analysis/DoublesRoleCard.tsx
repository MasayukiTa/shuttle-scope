import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'
import { EvidenceBadge } from '@/components/dashboard/EvidenceBadge'
import { ResearchNotice } from '@/components/dashboard/ResearchNotice'
import { AnalysisFilters } from '@/types'

interface PhaseBreakdown {
  score_phase: string
  inferred_role: string
  front_ratio: number
  back_ratio: number
  neutral_ratio: number
  n_shots: number
}

interface DoublesRoleData {
  inferred_role: string
  confidence_score: number
  front_ratio: number
  back_ratio: number
  neutral_ratio: number
  total_shots: number
  phase_breakdown: PhaseBreakdown[]
  note: string | null
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

const ROLE_LABELS: Record<string, string> = {
  front: 'フロント',
  back: 'バック',
  mixed: 'ミックス（不定）',
  unknown: '不明',
}
const ROLE_COLORS: Record<string, string> = {
  front: 'text-sky-400',
  back: 'text-amber-400',
  mixed: 'text-purple-400',
  unknown: 'text-gray-500',
}
const SCORE_PHASE_LABELS: Record<string, string> = {
  early: '序盤', mid: '中盤', deuce: 'デュース', endgame: '終盤',
}

function pct(v: number) {
  return `${(v * 100).toFixed(1)}%`
}

function RatioBar({ front, back, neutral }: { front: number; back: number; neutral: number }) {
  return (
    <div className="flex h-2 w-full rounded-full overflow-hidden gap-px">
      <div className="bg-sky-600" style={{ width: `${front * 100}%` }} title={`フロント ${pct(front)}`} />
      <div className="bg-amber-600" style={{ width: `${back * 100}%` }} title={`バック ${pct(back)}`} />
      <div className="bg-gray-600" style={{ width: `${neutral * 100}%` }} title={`ニュートラル ${pct(neutral)}`} />
    </div>
  )
}

export function DoublesRoleCard({ playerId, filters }: Props) {
  const filterApiParams = {
    ...(filters.result !== 'all' ? { result: filters.result } : {}),
    ...(filters.tournamentLevel ? { tournament_level: filters.tournamentLevel } : {}),
    ...(filters.dateFrom ? { date_from: filters.dateFrom } : {}),
    ...(filters.dateTo ? { date_to: filters.dateTo } : {}),
  }

  const { data, isLoading } = useQuery({
    queryKey: ['doubles-role', playerId, filters],
    queryFn: () =>
      apiGet<{ success: boolean; data: DoublesRoleData; meta: Meta }>(
        '/analysis/doubles_role',
        { player_id: playerId, ...filterApiParams }
      ),
  })

  const meta = data?.meta
  const roleData = data?.data

  return (
    <div className="bg-gray-800 rounded-lg p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-200">ダブルスロール推定（DB-1）</h3>
        <EvidenceBadge
          tier="research"
          evidenceLevel="exploratory"
          sampleSize={meta?.sample_size}
          recommendationAllowed={false}
        />
      </div>

      <ResearchNotice
        caution={meta?.caution ?? 'ロール推定はルールベース（DB-1）です。アノテーション品質・試合状況によって精度が変動します。'}
        assumptions="フロント/バックショット種別リストによるルールベース分類。HMMベース推定（DB-2）は未実装。"
        promotionCriteria="DB-2 HMM推定の実装・コーチによる妥当性確認・N≥100ラリー"
      />

      {isLoading ? (
        <p className="text-gray-500 text-sm text-center py-4">計算中...</p>
      ) : !roleData ? (
        <p className="text-gray-500 text-sm text-center py-4">ダブルスデータが不足しています</p>
      ) : (
        <div className="space-y-3">
          {/* メインロール表示 */}
          <div className="bg-gray-700/40 rounded px-3 py-2 space-y-2">
            <div className="flex items-center justify-between">
              <div>
                <span className="text-xs text-gray-400">推定ロール: </span>
                <span className={`text-sm font-semibold ${ROLE_COLORS[roleData.inferred_role] ?? 'text-gray-400'}`}>
                  {ROLE_LABELS[roleData.inferred_role] ?? roleData.inferred_role}
                </span>
              </div>
              <div className="text-right">
                <span className="text-[10px] text-gray-500">信頼スコア: </span>
                <span className={`text-xs font-medium ${roleData.confidence_score >= 0.7 ? 'text-emerald-400' : roleData.confidence_score >= 0.5 ? 'text-yellow-400' : 'text-orange-400'}`}>
                  {pct(roleData.confidence_score)}
                </span>
              </div>
            </div>

            <RatioBar
              front={roleData.front_ratio}
              back={roleData.back_ratio}
              neutral={roleData.neutral_ratio}
            />

            <div className="flex items-center gap-3 text-[10px] text-gray-500">
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-sm bg-sky-600 inline-block" />
                フロント {pct(roleData.front_ratio)}
              </span>
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-sm bg-amber-600 inline-block" />
                バック {pct(roleData.back_ratio)}
              </span>
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-sm bg-gray-600 inline-block" />
                ニュートラル {pct(roleData.neutral_ratio)}
              </span>
              <span className="ml-auto">N={roleData.total_shots}</span>
            </div>
          </div>

          {/* フェーズ別内訳 */}
          {roleData.phase_breakdown.length > 0 && (
            <div className="space-y-1">
              <p className="text-[10px] text-gray-500">スコアフェーズ別ロール</p>
              {roleData.phase_breakdown.map((ph, i) => (
                <div key={i} className="flex items-center gap-2 text-[10px]">
                  <span className="text-gray-500 w-12 shrink-0">
                    {SCORE_PHASE_LABELS[ph.score_phase] ?? ph.score_phase}
                  </span>
                  <span className={`w-16 font-medium ${ROLE_COLORS[ph.inferred_role] ?? 'text-gray-400'}`}>
                    {ROLE_LABELS[ph.inferred_role] ?? ph.inferred_role}
                  </span>
                  <div className="flex-1">
                    <RatioBar
                      front={ph.front_ratio}
                      back={ph.back_ratio}
                      neutral={ph.neutral_ratio}
                    />
                  </div>
                  <span className="text-gray-600 shrink-0">N={ph.n_shots}</span>
                </div>
              ))}
            </div>
          )}

          {roleData.note && (
            <p className="text-[10px] text-yellow-600/80">{roleData.note}</p>
          )}

          <p className="text-[10px] text-gray-600">
            バー左（青）= フロント系ショット比率、中央（橙）= バック系、右（灰）= ニュートラル。
          </p>
        </div>
      )}
    </div>
  )
}
