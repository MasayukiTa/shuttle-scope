import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiGet } from '@/api/client'
import { useAuth } from '@/hooks/useAuth'
import { ErrorBoundary } from '@/components/common/ErrorBoundary'
import { RoleGuard } from '@/components/common/RoleGuard'
import { AnalysisFilters, Player } from '@/types'
import { DashboardSectionNav, AdvancedSection } from '@/components/dashboard/DashboardSectionNav'
import { ShotWinLoss } from '@/components/analysis/ShotWinLoss'
import { SetComparison } from '@/components/analysis/SetComparison'
import { RallyLengthWinRate } from '@/components/analysis/RallyLengthWinRate'
import { PressurePerformance } from '@/components/analysis/PressurePerformance'
import { TransitionMatrix } from '@/components/analysis/TransitionMatrix'
import { PreLossPatterns } from '@/components/analysis/PreLossPatterns'
import { FirstReturnAnalysis } from '@/components/analysis/FirstReturnAnalysis'
import { SpatialDensityMap } from '@/components/analysis/SpatialDensityMap'
import { TemporalPerformance } from '@/components/analysis/TemporalPerformance'
import { PostLongRallyStats } from '@/components/analysis/PostLongRallyStats'
import { OpponentStats } from '@/components/analysis/OpponentStats'
import { OpponentTypeAffinity } from '@/components/analysis/OpponentTypeAffinity'
import { OpponentAdaptiveShots } from '@/components/analysis/OpponentAdaptiveShots'
import { PreMatchObservationAnalytics } from '@/components/analysis/PreMatchObservationAnalytics'
import { DoublesAnalysis } from '@/components/analysis/DoublesAnalysis'
import { PairPlaystyle } from '@/components/analysis/PairPlaystyle'
import { PairSynergyCard } from '@/components/analysis/PairSynergyCard'
import { WinLossComparison } from '@/components/analysis/WinLossComparison'
import { TournamentComparison } from '@/components/analysis/TournamentComparison'
import { EvidenceBadge } from '@/components/dashboard/EvidenceBadge'
import { ResearchNotice } from '@/components/dashboard/ResearchNotice'
import { useAnalysisMeta } from '@/hooks/useAnalysisMeta'
import { useCardTheme } from '@/hooks/useCardTheme'

interface MatchSummary {
  match_id: number
  opponent: string
  tournament: string
  tournament_level: string
  date: string | null
  result: 'win' | 'loss' | string | null
  rally_count: number
  format: string
  set_count: number
  set_scores: { set_num: number; score_player: number; score_opponent: number; won: boolean }[]
}

interface Props {
  playerId: number
  filters: AnalysisFilters
  matches: MatchSummary[]
  sortedPlayers: Player[]
}

export function DashboardAdvancedPage({ playerId, filters, matches, sortedPlayers }: Props) {
  const { t } = useTranslation()
  const [section, setSection] = useState<AdvancedSection>('shot')
  const [pairMode, setPairMode] = useState(false)
  const [partnerPlayerId, setPartnerPlayerId] = useState<number | null>(null)
  const { getMeta } = useAnalysisMeta()
  const { card, cardInner, textHeading, textSecondary, textMuted, textFaint, badge, border, isLight } = useCardTheme()
  const { role } = useAuth()

  // Override summary: admin/analyst/coach のみクエリ
  const { data: overridesResp } = useQuery({
    queryKey: ['promotion-overrides'],
    queryFn: () => apiGet<{ success: boolean; data: Record<string, { status: string; note: string; analyst: string }> }>(
      '/analysis/meta/promotion_overrides'
    ),
    staleTime: 30 * 1000,
    enabled: role === 'admin' || role === 'analyst' || role === 'coach',
  })
  const activeOverrides = Object.values(overridesResp?.data ?? {})
  const holdCount = activeOverrides.filter((o) => o.status === 'hold').length

  // セクション別 meta (backend meta 駆動)
  const transitionMeta = getMeta('transition')
  const temporalMeta = getMeta('temporal')
  const postLongRallyMeta = getMeta('post_long_rally')
  const pressureMeta = getMeta('pressure')
  // 追加 meta
  const preLossMeta = getMeta('pre_win_pre_loss')
  const firstReturnMeta = getMeta('first_return')
  const spatialMeta = getMeta('spatial_density')
  const opponentAffinityMeta = getMeta('opponent_affinity')
  const pairSynergyMeta = getMeta('pair_synergy')

  const restrictedFallback = (
    <div className={`${card} rounded-lg p-6 text-center text-sm ${textMuted}`}>{t('analysis.restricted')}</div>
  )

  const SectionTitle = ({ children }: { children: React.ReactNode }) => (
    <h2 className={`text-sm font-semibold ${textHeading} mb-0`}>{children}</h2>
  )

  return (
    <div className="space-y-4">
      {/* セクションナビ: スクロールで上へ流れる */}
      <div className={`-mx-6 px-6 py-2 flex items-center justify-between ${
        isLight ? 'bg-white border-b border-gray-200' : 'bg-gray-900 border-b border-gray-700/60'
      }`}>
        <div className="min-w-0 flex-1 overflow-hidden mr-2">
          <DashboardSectionNav active={section} onChange={setSection} />
        </div>
        <EvidenceBadge tier="advanced" evidenceLevel="practical_candidate" className="shrink-0" />
      </div>

      {/* Override summary バナー: admin/analyst/coach のみ、active override がある場合に表示 */}
      {activeOverrides.length > 0 && (role === 'admin' || role === 'analyst' || role === 'coach') && (
        <div className={`flex items-center gap-2 px-3 py-2 rounded-lg border-l-4 text-xs ${
          isLight
            ? 'bg-amber-50 border-amber-400 text-amber-800'
            : 'bg-amber-900/20 border-amber-600 text-amber-300'
        }`}>
          <span className="font-medium min-w-0 flex-1 truncate">
            {activeOverrides.length}件の分析に手動 Override が設定されています
          </span>
          {holdCount > 0 && (
            <span className={`shrink-0 px-1.5 py-0.5 rounded text-[10px] font-semibold ${
              isLight ? 'bg-orange-100 text-orange-700' : 'bg-orange-900/40 text-orange-300'
            }`}>
              保留 {holdCount}件
            </span>
          )}
          <span className={`shrink-0 text-[10px] ${isLight ? 'text-amber-600' : 'text-amber-500'}`}>
            Research タブで詳細確認
          </span>
        </div>
      )}

      {/* ── ショット分析 ── */}
      {section === 'shot' && (
        <ErrorBoundary>
          <RoleGuard allowedRoles={['analyst', 'coach']} fallback={restrictedFallback}>
            <div className="space-y-5">
              <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
                <div className={`${card} rounded-lg p-4`}>
                  <SectionTitle>{t('auto.DashboardAdvancedPage.k1')}</SectionTitle>
                  <ShotWinLoss playerId={playerId} filters={filters} />
                </div>
                <div className={`${card} rounded-lg p-4`}>
                  <SectionTitle>{t('auto.DashboardAdvancedPage.k2')}</SectionTitle>
                  <WinLossComparison playerId={playerId} filters={filters} />
                </div>
              </div>
              <div className={`${card} rounded-lg p-4`}>
                <SectionTitle>{t('auto.DashboardAdvancedPage.k3')}</SectionTitle>
                <TournamentComparison playerId={playerId} filters={filters} />
              </div>
            </div>
          </RoleGuard>
        </ErrorBoundary>
      )}

      {/* ── ラリー分析 ── */}
      {section === 'rally' && (
        <ErrorBoundary>
          <div className="space-y-4">
            {pressureMeta?.caution && (
              <ResearchNotice
                caution={pressureMeta.caution}
                assumptions={pressureMeta.assumptions ?? undefined}
                promotionCriteria={pressureMeta.promotion_criteria ?? undefined}
              />
            )}
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
              <div className={`${card} rounded-lg p-4`}>
                <SectionTitle>{t('auto.DashboardAdvancedPage.k4')}</SectionTitle>
                <RallyLengthWinRate playerId={playerId} filters={filters} />
              </div>
              <div className={`${card} rounded-lg p-4 space-y-2`}>
                <div className="flex items-center justify-between">
                  <SectionTitle>{t('auto.DashboardAdvancedPage.k5')}</SectionTitle>
                  <EvidenceBadge
                    tier="advanced"
                    evidenceLevel={(pressureMeta?.evidence_level as any) ?? 'practical_candidate'}
                    recommendationAllowed={false}
                  />
                </div>
                <PressurePerformance playerId={playerId} filters={filters} />
              </div>
            </div>
          </div>
        </ErrorBoundary>
      )}

      {/* ── 遷移マトリクス ── */}
      {section === 'transition' && (
        <ErrorBoundary>
          <RoleGuard allowedRoles={['analyst', 'coach']} fallback={restrictedFallback}>
            <div className={`${card} rounded-lg p-4 space-y-2`}>
              <div className="flex items-center justify-between">
                <SectionTitle>{t('auto.DashboardAdvancedPage.k6')}</SectionTitle>
                <EvidenceBadge
                  tier="advanced"
                  evidenceLevel={(transitionMeta?.evidence_level as any) ?? 'practical_candidate'}
                  recommendationAllowed={false}
                />
              </div>
              {transitionMeta?.caution && (
                <ResearchNotice
                  caution={transitionMeta.caution}
                  assumptions={transitionMeta.assumptions ?? undefined}
                  promotionCriteria={transitionMeta.promotion_criteria ?? undefined}
                />
              )}
              <TransitionMatrix playerId={playerId} filters={filters} />
            </div>
          </RoleGuard>
        </ErrorBoundary>
      )}

      {/* ── 空間分析 ── */}
      {section === 'spatial' && (
        <ErrorBoundary>
          <div className="space-y-5">
            {(preLossMeta?.caution || firstReturnMeta?.caution) && (
              <ResearchNotice
                caution={preLossMeta?.caution ?? firstReturnMeta?.caution ?? ''}
                assumptions={preLossMeta?.assumptions ?? undefined}
                promotionCriteria={preLossMeta?.promotion_criteria ?? undefined}
              />
            )}
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
              <div className={`${card} rounded-lg p-4 space-y-2`}>
                <div className="flex items-center justify-between">
                  <SectionTitle>{t('analysis.pre_loss.title')}</SectionTitle>
                  <EvidenceBadge
                    tier="advanced"
                    evidenceLevel={(preLossMeta?.evidence_level as any) ?? 'practical_candidate'}
                    recommendationAllowed={false}
                  />
                </div>
                <PreLossPatterns playerId={playerId} filters={filters} />
              </div>
              <div className={`${card} rounded-lg p-4 space-y-2`}>
                <div className="flex items-center justify-between">
                  <SectionTitle>{t('analysis.first_return.title')}</SectionTitle>
                  <EvidenceBadge
                    tier="advanced"
                    evidenceLevel={(firstReturnMeta?.evidence_level as any) ?? 'practical_candidate'}
                    recommendationAllowed={false}
                  />
                </div>
                <FirstReturnAnalysis playerId={playerId} filters={filters} />
              </div>
            </div>
            <RoleGuard allowedRoles={['analyst', 'coach']}>
              {spatialMeta?.caution && (
                <ResearchNotice
                  caution={spatialMeta.caution}
                  assumptions={spatialMeta.assumptions ?? undefined}
                  promotionCriteria={spatialMeta.promotion_criteria ?? undefined}
                />
              )}
              <SpatialDensityMap playerId={playerId} />
            </RoleGuard>
          </div>
        </ErrorBoundary>
      )}

      {/* ── 時間・体力 ── */}
      {section === 'temporal' && (
        <ErrorBoundary>
          <div className="space-y-4">
            {(temporalMeta?.caution || postLongRallyMeta?.caution) && (
              <ResearchNotice
                caution={temporalMeta?.caution ?? postLongRallyMeta?.caution ?? ''}
                assumptions={temporalMeta?.assumptions ?? undefined}
                promotionCriteria={temporalMeta?.promotion_criteria ?? undefined}
              />
            )}
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
              <div className={`${card} rounded-lg p-4 space-y-2`}>
                <div className="flex items-center justify-between">
                  <SectionTitle>{t('analysis.temporal.title')}</SectionTitle>
                  <EvidenceBadge
                    tier="advanced"
                    evidenceLevel={(temporalMeta?.evidence_level as any) ?? 'directional'}
                    recommendationAllowed={false}
                  />
                </div>
                <TemporalPerformance playerId={playerId} filters={filters} />
              </div>
              <div className={`${card} rounded-lg p-4 space-y-2`}>
                <div className="flex items-center justify-between">
                  <SectionTitle>{t('analysis.post_long_rally.title')}</SectionTitle>
                  <EvidenceBadge
                    tier="advanced"
                    evidenceLevel={(postLongRallyMeta?.evidence_level as any) ?? 'directional'}
                    recommendationAllowed={false}
                  />
                </div>
                <PostLongRallyStats playerId={playerId} filters={filters} />
              </div>
            </div>
          </div>
        </ErrorBoundary>
      )}

      {/* ── 対戦相手 ── */}
      {section === 'opponent' && (
        <ErrorBoundary>
          <RoleGuard allowedRoles={['analyst', 'coach']} fallback={restrictedFallback}>
            <div className="space-y-5">
              {opponentAffinityMeta?.caution && (
                <ResearchNotice
                  caution={opponentAffinityMeta.caution}
                  assumptions={opponentAffinityMeta.assumptions ?? undefined}
                  promotionCriteria={opponentAffinityMeta.promotion_criteria ?? undefined}
                />
              )}
              <div className={`${card} rounded-lg p-4`}>
                <SectionTitle>{t('analysis.opponent_stats.title')}</SectionTitle>
                <OpponentStats playerId={playerId} />
              </div>
              <div className={`${card} rounded-lg p-4 space-y-2`}>
                <div className="flex items-center justify-between">
                  <SectionTitle>{t('analysis.opponent_type_affinity.title')}</SectionTitle>
                  <EvidenceBadge
                    tier="research"
                    evidenceLevel={(opponentAffinityMeta?.evidence_level as any) ?? 'exploratory'}
                    recommendationAllowed={false}
                  />
                </div>
                <p className={`text-xs ${textMuted}`}>{t('analysis.opponent_type_affinity.subtitle')}</p>
                <OpponentTypeAffinity playerId={playerId} filters={filters} />
              </div>
              <OpponentAdaptiveShots playerId={playerId} />
              <div className={`${card} rounded-lg p-4`}>
                <div className="flex items-center justify-between mb-3">
                  <SectionTitle>{t('observation_analytics.title', '補助観察インサイト')}</SectionTitle>
                  <span className={`text-[9px] border rounded px-1.5 py-0.5 ${badge}`}>{t('auto.DashboardAdvancedPage.k7')}</span>
                </div>
                <PreMatchObservationAnalytics playerId={playerId} />
              </div>
            </div>
          </RoleGuard>
        </ErrorBoundary>
      )}

      {/* ── ダブルス ── */}
      {section === 'doubles' && (
        <ErrorBoundary>
          <div className="space-y-5">
            <DoublesAnalysis playerId={playerId} allMatches={matches} />

            {/* ペアモードトグル */}
            {sortedPlayers.filter((p) => p.is_target).length >= 2 && (
              <div className={`flex items-center gap-3 ${card} rounded-lg px-4 py-3`}>
                <span className={`text-xs ${textSecondary}`}>{t('auto.DashboardAdvancedPage.k8')}</span>
                <button
                  onClick={() => { setPairMode((v) => !v); setPartnerPlayerId(null) }}
                  className={`relative w-10 h-5 rounded-full transition-colors ${pairMode ? 'bg-blue-500' : (isLight ? 'bg-gray-300' : 'bg-gray-600')}`}
                >
                  <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${pairMode ? 'translate-x-5' : ''}`} />
                </button>
                {pairMode && (
                  <select
                    className={`border text-xs rounded px-2 py-1 ${isLight ? 'bg-white border-gray-300 text-gray-700' : 'bg-gray-700 border-gray-600 text-white'}`}
                    value={partnerPlayerId ?? ''}
                    onChange={(e) => setPartnerPlayerId(e.target.value ? Number(e.target.value) : null)}
                  >
                    <option value="">{t('auto.DashboardAdvancedPage.k9')}</option>
                    {sortedPlayers.filter((p) => p.is_target && p.id !== playerId).map((p) => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </select>
                )}
              </div>
            )}

            {pairMode && partnerPlayerId && (
              <div className={`${card} rounded-lg p-4`}>
                <SectionTitle>{t('analysis.pair_playstyle.title')}</SectionTitle>
                <p className={`text-xs mb-3 ${textMuted}`}>{t('analysis.pair_playstyle.subtitle')}</p>
                <PairPlaystyle
                  playerAId={playerId}
                  playerBId={partnerPlayerId}
                  playerAName={sortedPlayers.find((p) => p.id === playerId)?.name}
                  playerBName={sortedPlayers.find((p) => p.id === partnerPlayerId)?.name}
                />
              </div>
            )}
            {pairSynergyMeta?.caution && (
              <ResearchNotice
                caution={pairSynergyMeta.caution}
                assumptions={pairSynergyMeta.assumptions ?? undefined}
                promotionCriteria={pairSynergyMeta.promotion_criteria ?? undefined}
              />
            )}
            <PairSynergyCard playerId={playerId} />
          </div>
        </ErrorBoundary>
      )}
    </div>
  )
}
