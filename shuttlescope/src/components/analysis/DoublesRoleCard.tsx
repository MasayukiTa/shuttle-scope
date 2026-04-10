import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'
import { EvidenceBadge } from '@/components/dashboard/EvidenceBadge'
import { ResearchNotice } from '@/components/dashboard/ResearchNotice'
import { useCardTheme } from '@/hooks/useCardTheme'
import { AnalysisFilters } from '@/types'

// ─── CV ロール照合型 ──────────────────────────────────────────────────────────

interface CVRoleSignal {
  cv_available: boolean
  shot_role: string
  cv_formation_style: string
  agreement: 'consistent' | 'partial' | 'inconsistent' | 'unknown'
  agreement_score: number
  player_a_cv_role_hint: string | null
  player_b_cv_role_hint: string | null
  cv_adjusted_note: string
}

interface CVAnalysisResp {
  available: boolean
  cv_role_signal?: CVRoleSignal | null
}

interface RecentMatchRef {
  id: number
  match_date: string | null
}

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
  phase_breakdown: PhaseBreakdown[] | undefined
  note: string | null
}

interface PerMatchRole {
  match_id: number
  inferred_role: string
  confidence: number
  n_shots: number
  season: string
}

interface SeasonVariation {
  season: string
  dominant_role: string
  n_matches: number
  role_counts: Record<string, number>
}

interface StabilityData {
  role_stability_score: number
  dominant_role: string
  n_matches_analyzed: number
  per_match_roles: PerMatchRole[]
  season_variation: SeasonVariation[]
  consistency_label: string
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

const SCORE_PHASE_LABELS: Record<string, string> = {
  early: '序盤', mid: '中盤', deuce: 'デュース', endgame: '終盤',
}

function getRoleColor(role: string, isLight: boolean): string {
  const map: Record<string, [string, string]> = {
    front: ['text-sky-600', 'text-sky-400'],
    back: ['text-amber-600', 'text-amber-400'],
    mixed: ['text-purple-600', 'text-purple-400'],
    unknown: ['text-gray-500', 'text-gray-500'],
  }
  const pair = map[role]
  if (!pair) return isLight ? 'text-gray-500' : 'text-gray-500'
  return isLight ? pair[0] : pair[1]
}

const ROLE_LABELS: Record<string, string> = {
  front: 'フロント',
  back: 'バック',
  mixed: 'ミックス（不定）',
  unknown: '不明',
}

const CONSISTENCY_LABELS: Record<string, string> = {
  consistent: '一貫',
  moderate: '普通',
  volatile: '不安定',
  insufficient_data: 'データ不足',
}

function getConsistencyColor(label: string, isLight: boolean): string {
  const map: Record<string, [string, string]> = {
    consistent: ['text-emerald-600', 'text-emerald-400'],
    moderate: ['text-amber-600', 'text-amber-400'],
    volatile: ['text-red-600', 'text-red-400'],
    insufficient_data: ['text-gray-500', 'text-gray-500'],
  }
  const pair = map[label]
  if (!pair) return isLight ? 'text-gray-500' : 'text-gray-500'
  return isLight ? pair[0] : pair[1]
}

function pct(v: number) {
  return `${(v * 100).toFixed(1)}%`
}

function RatioBar({ front, back, neutral }: { front: number; back: number; neutral: number }) {
  return (
    <div className="flex h-2 w-full rounded-full overflow-hidden gap-px">
      <div className="bg-sky-600" style={{ width: `${front * 100}%` }} title={`フロント ${pct(front)}`} />
      <div className="bg-amber-600" style={{ width: `${back * 100}%` }} title={`バック ${pct(back)}`} />
      <div className="bg-gray-500" style={{ width: `${neutral * 100}%` }} title={`ニュートラル ${pct(neutral)}`} />
    </div>
  )
}

export function DoublesRoleCard({ playerId, filters }: Props) {
  const { card, cardInner, cardInnerAlt, textHeading, textSecondary, textMuted, textFaint, loading, isLight } = useCardTheme()
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

  const { data: stabilityResp } = useQuery({
    queryKey: ['doubles-role-stability', playerId, filters],
    queryFn: () =>
      apiGet<{ success: boolean; data: StabilityData; meta: Meta }>(
        '/analysis/doubles_role_stability',
        { player_id: playerId, ...filterApiParams }
      ),
  })

  // CV ロール照合: 最新試合の cv_role_signal を取得
  const { data: matchesResp } = useQuery({
    queryKey: ['player-matches-for-cv-role', playerId],
    queryFn: () =>
      apiGet<{ success: boolean; data: RecentMatchRef[] }>('/matches', { player_id: playerId }),
    enabled: !!playerId,
  })
  const recentMatchId = matchesResp?.data?.[0]?.id ?? null
  const { data: cvResp } = useQuery({
    queryKey: ['yolo-doubles-analysis-for-role', recentMatchId],
    queryFn: () =>
      apiGet<{ success: boolean; data: CVAnalysisResp }>(`/yolo/doubles_analysis/${recentMatchId}`),
    enabled: !!recentMatchId,
  })
  const cvRoleSignal: CVRoleSignal | null | undefined = cvResp?.data?.cv_role_signal

  const meta = data?.meta
  const roleData = data?.data
  const stability = stabilityResp?.data

  return (
    <div className={`${card} rounded-lg p-4 space-y-3`}>
      <div className="flex items-center justify-between">
        <h3 className={`text-sm font-semibold ${textHeading}`}>ダブルスロール推定（DB-1/2）</h3>
        <EvidenceBadge
          tier="research"
          evidenceLevel="exploratory"
          sampleSize={meta?.sample_size}
          recommendationAllowed={false}
        />
      </div>

      <ResearchNotice
        caution={meta?.caution ?? 'ロール推定はルールベース（DB-1）です。アノテーション品質・試合状況によって精度が変動します。'}
        assumptions="フロント/バックショット種別リストによるルールベース分類。HMM（DB-2）はBaum-Welchで学習。"
        promotionCriteria="DB-2 HMM推定の安定確認・コーチによる妥当性確認・N≥100ラリー"
      />

      {isLoading ? (
        <p className={`text-sm text-center py-4 ${loading}`}>計算中...</p>
      ) : !roleData ? (
        <p className={`text-sm text-center py-4 ${loading}`}>ダブルスデータが不足しています</p>
      ) : (
        <div className="space-y-3">
          {/* メインロール表示 */}
          <div className={`${cardInner} rounded px-3 py-2 space-y-2`}>
            <div className="flex items-center justify-between">
              <div>
                <span className={`text-xs ${textSecondary}`}>推定ロール: </span>
                <span className={`text-sm font-semibold ${getRoleColor(roleData.inferred_role, isLight)}`}>
                  {ROLE_LABELS[roleData.inferred_role] ?? roleData.inferred_role}
                </span>
              </div>
              <div className="text-right">
                <span className={`text-[10px] ${textMuted}`}>信頼スコア: </span>
                <span className={`text-xs font-medium ${roleData.confidence_score >= 0.7 ? (isLight ? 'text-emerald-600' : 'text-emerald-400') : roleData.confidence_score >= 0.5 ? (isLight ? 'text-amber-600' : 'text-yellow-400') : (isLight ? 'text-orange-600' : 'text-orange-400')}`}>
                  {pct(roleData.confidence_score)}
                </span>
              </div>
            </div>

            <RatioBar
              front={roleData.front_ratio}
              back={roleData.back_ratio}
              neutral={roleData.neutral_ratio}
            />

            <div className={`flex items-center gap-3 text-[10px] ${textMuted}`}>
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-sm bg-sky-600 inline-block" />
                フロント {pct(roleData.front_ratio)}
              </span>
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-sm bg-amber-600 inline-block" />
                バック {pct(roleData.back_ratio)}
              </span>
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-sm bg-gray-500 inline-block" />
                ニュートラル {pct(roleData.neutral_ratio)}
              </span>
              <span className="ml-auto">N={roleData.total_shots}</span>
            </div>
          </div>

          {/* フェーズ別内訳 */}
          {(roleData.phase_breakdown ?? []).length > 0 && (
            <div className="space-y-1">
              <p className={`text-[10px] ${textMuted}`}>スコアフェーズ別ロール</p>
              {(roleData.phase_breakdown ?? []).map((ph, i) => (
                <div key={i} className="flex items-center gap-2 text-[10px]">
                  <span className={`w-12 shrink-0 ${textMuted}`}>
                    {SCORE_PHASE_LABELS[ph.score_phase] ?? ph.score_phase}
                  </span>
                  <span className={`w-16 font-medium ${getRoleColor(ph.inferred_role, isLight)}`}>
                    {ROLE_LABELS[ph.inferred_role] ?? ph.inferred_role}
                  </span>
                  <div className="flex-1">
                    <RatioBar
                      front={ph.front_ratio}
                      back={ph.back_ratio}
                      neutral={ph.neutral_ratio}
                    />
                  </div>
                  <span className={`shrink-0 ${textFaint}`}>N={ph.n_shots}</span>
                </div>
              ))}
            </div>
          )}

          {roleData.note && (
            <p className={`text-[10px] ${isLight ? 'text-amber-700' : 'text-yellow-600/80'}`}>{roleData.note}</p>
          )}

          {/* CV 位置照合セクション */}
          {cvRoleSignal?.cv_available && (
            <div className={`${cardInnerAlt} rounded px-3 py-2 space-y-1.5`}>
              <div className="flex items-center justify-between">
                <p className={`text-[10px] font-medium ${textSecondary}`}>
                  CV 位置照合
                  {recentMatchId && (
                    <span className={`ml-1 font-normal ${textFaint}`}>試合 #{recentMatchId}</span>
                  )}
                </p>
                <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${
                  cvRoleSignal.agreement === 'consistent'
                    ? isLight ? 'bg-emerald-100 text-emerald-700' : 'bg-emerald-900/40 text-emerald-300'
                    : cvRoleSignal.agreement === 'inconsistent'
                    ? isLight ? 'bg-red-100 text-red-700' : 'bg-red-900/40 text-red-300'
                    : isLight ? 'bg-amber-100 text-amber-700' : 'bg-amber-900/40 text-amber-300'
                }`}>
                  {cvRoleSignal.agreement === 'consistent' ? '一致'
                    : cvRoleSignal.agreement === 'inconsistent' ? '不一致'
                    : cvRoleSignal.agreement === 'partial' ? '部分一致'
                    : '不明'}
                </span>
              </div>
              <div className={`flex items-center gap-3 text-[10px] ${textMuted}`}>
                <span>CV陣形: <span className={textSecondary}>{cvRoleSignal.cv_formation_style}</span></span>
                <span>照合スコア: <span className={textSecondary}>{Math.round(cvRoleSignal.agreement_score * 100)}%</span></span>
              </div>
              {(cvRoleSignal.player_a_cv_role_hint || cvRoleSignal.player_b_cv_role_hint) && (
                <div className={`flex gap-3 text-[10px] ${textFaint}`}>
                  {cvRoleSignal.player_a_cv_role_hint && (
                    <span>A: <span className="text-blue-400">{cvRoleSignal.player_a_cv_role_hint}</span></span>
                  )}
                  {cvRoleSignal.player_b_cv_role_hint && (
                    <span>B: <span className="text-amber-400">{cvRoleSignal.player_b_cv_role_hint}</span></span>
                  )}
                </div>
              )}
              {cvRoleSignal.cv_adjusted_note && (
                <p className={`text-[9px] italic ${textFaint}`}>{cvRoleSignal.cv_adjusted_note}</p>
              )}
            </div>
          )}

          {/* DB-3 安定性セクション */}
          {stability && stability.n_matches_analyzed > 0 && (
            <div className={`${cardInnerAlt} rounded px-3 py-2 space-y-1.5`}>
              <div className="flex items-center justify-between">
                <p className={`text-[10px] font-medium ${textSecondary}`}>ロール安定性（DB-3）</p>
                <span className={`text-[10px] font-semibold ${getConsistencyColor(stability.consistency_label, isLight)}`}>
                  {CONSISTENCY_LABELS[stability.consistency_label] ?? stability.consistency_label}
                </span>
              </div>
              <div className="flex items-center gap-3 text-[10px]">
                <span className={textMuted}>
                  安定性スコア:
                  <span className={`ml-1 font-medium ${getConsistencyColor(stability.consistency_label, isLight)}`}>
                    {pct(stability.role_stability_score)}
                  </span>
                </span>
                <span className={textFaint}>({stability.n_matches_analyzed}試合で分析)</span>
              </div>
              {/* シーズン変動 */}
              {stability.season_variation.length > 1 && (
                <div className="flex flex-wrap gap-2">
                  {stability.season_variation.map((sv) => (
                    <span key={sv.season} className="text-[10px]">
                      <span className={textFaint}>{sv.season}: </span>
                      <span className={`${getRoleColor(sv.dominant_role, isLight)} font-medium`}>
                        {ROLE_LABELS[sv.dominant_role] ?? sv.dominant_role}
                      </span>
                      <span className={textFaint}> ({sv.n_matches}試)</span>
                    </span>
                  ))}
                </div>
              )}
              {stability.note && (
                <p className={`text-[10px] ${isLight ? 'text-amber-700' : 'text-amber-500/80'}`}>{stability.note}</p>
              )}
            </div>
          )}

          <p className={`text-[10px] ${textFaint}`}>
            バー左（青）= フロント系ショット比率、中央（橙）= バック系、右（灰）= ニュートラル。
          </p>
        </div>
      )}
    </div>
  )
}
