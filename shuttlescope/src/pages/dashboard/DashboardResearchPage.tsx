import { useTranslation } from 'react-i18next'
import { ErrorBoundary } from '@/components/common/ErrorBoundary'
import { RoleGuard } from '@/components/common/RoleGuard'
import { AnalysisFilters } from '@/types'
import { ResearchNotice } from '@/components/dashboard/ResearchNotice'
import { EvidenceBadge } from '@/components/dashboard/EvidenceBadge'
import { useCardTheme } from '@/hooks/useCardTheme'
import { MarkovEPV } from '@/components/analysis/MarkovEPV'
import { CounterfactualShots } from '@/components/analysis/CounterfactualShots'
import { SpatialDensityMap } from '@/components/analysis/SpatialDensityMap'
import { StateEPVCard } from '@/components/analysis/StateEPVCard'
import { StateActionValueCard } from '@/components/analysis/StateActionValueCard'
import { HazardFatigueCard } from '@/components/analysis/HazardFatigueCard'
import { CounterfactualV2Card } from '@/components/analysis/CounterfactualV2Card'
import { BayesMatchupCard } from '@/components/analysis/BayesMatchupCard'
import { OpponentPolicyCard } from '@/components/analysis/OpponentPolicyCard'
import { DoublesRoleCard } from '@/components/analysis/DoublesRoleCard'
import { ShotInfluenceV2Card } from '@/components/analysis/ShotInfluenceV2Card'
import { PromotionStatusCard } from '@/components/analysis/PromotionStatusCard'
import { YoloCVPositionCard } from '@/components/analysis/YoloCVPositionCard'
import { useAnalysisMeta } from '@/hooks/useAnalysisMeta'

interface Props {
  playerId: number
  filters: AnalysisFilters
}

export function DashboardResearchPage({ playerId, filters }: Props) {
  const { t } = useTranslation()
  const { getMeta } = useAnalysisMeta()
  const { card, textHeading, textMuted, textFaint, badge, isLight } = useCardTheme()

  const epvMeta = getMeta('epv')
  const cfMeta = getMeta('counterfactual')
  const spatialMeta = getMeta('spatial_density')

  const restrictedFallback = (
    <div className={`${card} rounded-lg p-6 text-center text-sm ${textMuted}`}>{t('analysis.restricted')}</div>
  )
  const analystFallback = (
    <div className={`${card} rounded-lg p-6 text-center text-sm ${textMuted}`}>昇格ワークフローはアナリスト向けです</div>
  )

  return (
    <div className="space-y-5">
      {/* ページレベルの注意 */}
      <ResearchNotice
        caution="このページの分析はすべて探索的・研究段階です。実戦判断や選手評価の根拠として単独使用しないでください。"
        reason="サンプルサイズ・モデル前提・校正品質がいずれも実用水準に達していない項目を含みます。"
        promotionCriteria="各項目が実用移行するには、十分なサンプルサイズ・CI品質・コーチ有用性の確認が必要です。"
      />

      {/* EPV分析（Markov） */}
      <ErrorBoundary>
        <RoleGuard allowedRoles={['analyst', 'coach']} fallback={restrictedFallback}>
          <div className={`${card} rounded-lg p-4 space-y-3`}>
            <div className="flex items-center justify-between">
              <h2 className={`text-sm font-semibold ${textHeading}`}>{t('analysis.epv.title')}</h2>
              <EvidenceBadge
                tier="research"
                evidenceLevel={(epvMeta?.evidence_level as any) ?? 'directional'}
                recommendationAllowed={false}
              />
            </div>
            <ResearchNotice
              caution={epvMeta?.caution ?? 'EPVはMarkovモデルに基づく探索的指標です。'}
              assumptions={epvMeta?.assumptions ?? '定常マルコフ過程・独立ラリー仮定'}
              promotionCriteria={epvMeta?.promotion_criteria ?? undefined}
            />
            <MarkovEPV playerId={playerId} filters={filters} />
          </div>
        </RoleGuard>
      </ErrorBoundary>

      {/* 反事実的ショット比較 */}
      <ErrorBoundary>
        <RoleGuard allowedRoles={['analyst', 'coach']} fallback={restrictedFallback}>
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className={`text-xs font-semibold uppercase tracking-wider ${textMuted}`}>反事実的ショット比較</h3>
              <EvidenceBadge
                tier="research"
                evidenceLevel={(cfMeta?.evidence_level as any) ?? 'exploratory'}
                recommendationAllowed={false}
              />
            </div>
            <ResearchNotice
              caution={cfMeta?.caution ?? '反事実的分析は仮説的シナリオの比較です。'}
              assumptions={cfMeta?.assumptions ?? undefined}
              promotionCriteria={cfMeta?.promotion_criteria ?? undefined}
            />
            <CounterfactualShots playerId={playerId} />
          </div>
        </RoleGuard>
      </ErrorBoundary>

      {/* コート密度マップ（研究段階） */}
      <ErrorBoundary>
        <RoleGuard allowedRoles={['analyst', 'coach']} fallback={restrictedFallback}>
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className={`text-xs font-semibold uppercase tracking-wider ${textMuted}`}>コート空間密度マップ</h3>
              <EvidenceBadge
                tier="research"
                evidenceLevel={(spatialMeta?.evidence_level as any) ?? 'exploratory'}
              />
            </div>
            <ResearchNotice
              caution={spatialMeta?.caution ?? '空間密度マップはコート上の打点・着地点の密度分布を可視化したものです。'}
              assumptions={spatialMeta?.assumptions ?? undefined}
              promotionCriteria={spatialMeta?.promotion_criteria ?? undefined}
            />
            <SpatialDensityMap playerId={playerId} />
          </div>
        </RoleGuard>
      </ErrorBoundary>

      {/* ── Research Spine RS-1: 状態ベース EPV ── */}
      <ErrorBoundary>
        <RoleGuard allowedRoles={['analyst', 'coach']} fallback={restrictedFallback}>
          <StateEPVCard playerId={playerId} filters={filters} />
        </RoleGuard>
      </ErrorBoundary>

      {/* ── Research Spine RS-2: 状態-行動価値 ── */}
      <ErrorBoundary>
        <RoleGuard allowedRoles={['analyst', 'coach']} fallback={restrictedFallback}>
          <StateActionValueCard playerId={playerId} filters={filters} />
        </RoleGuard>
      </ErrorBoundary>

      {/* ── Research Spine RS-3: ハザード・疲労モデル ── */}
      <ErrorBoundary>
        <RoleGuard allowedRoles={['analyst', 'coach']} fallback={restrictedFallback}>
          <HazardFatigueCard playerId={playerId} filters={filters} />
        </RoleGuard>
      </ErrorBoundary>

      {/* ── Research Spine RS-3: 反事実的ショット v2 ── */}
      <ErrorBoundary>
        <RoleGuard allowedRoles={['analyst', 'coach']} fallback={restrictedFallback}>
          <CounterfactualV2Card playerId={playerId} filters={filters} />
        </RoleGuard>
      </ErrorBoundary>

      {/* ── Research Spine RS-4: ベイズ対戦予測 ── */}
      <ErrorBoundary>
        <RoleGuard allowedRoles={['analyst', 'coach']} fallback={restrictedFallback}>
          <BayesMatchupCard playerId={playerId} filters={filters} />
        </RoleGuard>
      </ErrorBoundary>

      {/* ── Research Spine RS-4: 対戦相手ポリシー ── */}
      <ErrorBoundary>
        <RoleGuard allowedRoles={['analyst', 'coach']} fallback={restrictedFallback}>
          <OpponentPolicyCard playerId={playerId} filters={filters} />
        </RoleGuard>
      </ErrorBoundary>

      {/* ── Research Spine RS-5: ダブルスロール推定 ── */}
      <ErrorBoundary>
        <RoleGuard allowedRoles={['analyst', 'coach']} fallback={restrictedFallback}>
          <DoublesRoleCard playerId={playerId} filters={filters} />
        </RoleGuard>
      </ErrorBoundary>

      {/* ── Spine 4: ショット影響度 v2（状態条件付き） ── */}
      <ErrorBoundary>
        <RoleGuard allowedRoles={['analyst', 'coach']} fallback={restrictedFallback}>
          <ShotInfluenceV2Card playerId={playerId} filters={filters} />
        </RoleGuard>
      </ErrorBoundary>

      {/* ── CV ポジション解析（YOLO / TrackNet assisted） ── */}
      <ErrorBoundary>
        <RoleGuard allowedRoles={['analyst', 'coach']} fallback={restrictedFallback}>
          <YoloCVPositionCard playerId={playerId} filters={filters} />
        </RoleGuard>
      </ErrorBoundary>

      {/* ── 昇格ワークフロー ── */}
      <ErrorBoundary>
        <RoleGuard allowedRoles={['analyst']} fallback={analystFallback}>
          <PromotionStatusCard playerId={playerId} filters={filters} />
        </RoleGuard>
      </ErrorBoundary>
    </div>
  )
}
