import { useTranslation } from 'react-i18next'
import { ErrorBoundary } from '@/components/common/ErrorBoundary'
import { RoleGuard } from '@/components/common/RoleGuard'
import { AnalysisFilters } from '@/types'
import { ResearchNotice } from '@/components/dashboard/ResearchNotice'
import { EvidenceBadge } from '@/components/dashboard/EvidenceBadge'
import { MarkovEPV } from '@/components/analysis/MarkovEPV'
import { CounterfactualShots } from '@/components/analysis/CounterfactualShots'
import { SpatialDensityMap } from '@/components/analysis/SpatialDensityMap'
import { StateEPVCard } from '@/components/analysis/StateEPVCard'
import { StateActionValueCard } from '@/components/analysis/StateActionValueCard'
import { HazardFatigueCard } from '@/components/analysis/HazardFatigueCard'
import { CounterfactualV2Card } from '@/components/analysis/CounterfactualV2Card'

interface Props {
  playerId: number
  filters: AnalysisFilters
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h2 className="text-sm font-semibold text-gray-300 mb-0">{children}</h2>
}

export function DashboardResearchPage({ playerId, filters }: Props) {
  const { t } = useTranslation()

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
        <RoleGuard
          allowedRoles={['analyst', 'coach']}
          fallback={<div className="bg-gray-800 rounded-lg p-6 text-center text-gray-500 text-sm">{t('analysis.restricted')}</div>}
        >
          <div className="bg-gray-800 rounded-lg p-4 space-y-3">
            <div className="flex items-center justify-between">
              <SectionTitle>{t('analysis.epv.title')}</SectionTitle>
              <EvidenceBadge tier="research" evidenceLevel="directional" recommendationAllowed={false} />
            </div>
            <ResearchNotice
              caution="EPVはMarkovモデルに基づく探索的指標です。スコア重み付けは近似値であり、実際の試合判断に直結するものではありません。"
              assumptions="定常マルコフ過程・独立ラリー仮定"
              promotionCriteria="校正品質・十分なサンプルサイズ・コーチ有用性テスト"
            />
            <MarkovEPV playerId={playerId} filters={filters} />
          </div>
        </RoleGuard>
      </ErrorBoundary>

      {/* 反事実的ショット比較 */}
      <ErrorBoundary>
        <RoleGuard
          allowedRoles={['analyst', 'coach']}
          fallback={<div className="bg-gray-800 rounded-lg p-6 text-center text-gray-500 text-sm">{t('analysis.restricted')}</div>}
        >
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">反事実的ショット比較</h3>
              <EvidenceBadge tier="research" evidenceLevel="exploratory" recommendationAllowed={false} />
            </div>
            <ResearchNotice
              caution="反事実的分析は仮説的シナリオの比較です。現実の選択と乖離した前提を含みます。"
              reason="ショット選択の代替シナリオを探索的に評価するための参考指標です。"
            />
            <CounterfactualShots playerId={playerId} />
          </div>
        </RoleGuard>
      </ErrorBoundary>

      {/* コート密度マップ（研究段階） */}
      <ErrorBoundary>
        <RoleGuard
          allowedRoles={['analyst', 'coach']}
          fallback={<div className="bg-gray-800 rounded-lg p-6 text-center text-gray-500 text-sm">{t('analysis.restricted')}</div>}
        >
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">コート空間密度マップ</h3>
              <EvidenceBadge tier="research" evidenceLevel="exploratory" />
            </div>
            <ResearchNotice
              caution="空間密度マップはコート上の打点・着地点の密度分布を可視化したものです。統計的有意性の検定は行っていません。"
            />
            <SpatialDensityMap playerId={playerId} />
          </div>
        </RoleGuard>
      </ErrorBoundary>

      {/* ── Research Spine RS-1: 状態ベース EPV ── */}
      <ErrorBoundary>
        <RoleGuard
          allowedRoles={['analyst', 'coach']}
          fallback={<div className="bg-gray-800 rounded-lg p-6 text-center text-gray-500 text-sm">{t('analysis.restricted')}</div>}
        >
          <StateEPVCard playerId={playerId} filters={filters} />
        </RoleGuard>
      </ErrorBoundary>

      {/* ── Research Spine RS-2: 状態-行動価値 ── */}
      <ErrorBoundary>
        <RoleGuard
          allowedRoles={['analyst', 'coach']}
          fallback={<div className="bg-gray-800 rounded-lg p-6 text-center text-gray-500 text-sm">{t('analysis.restricted')}</div>}
        >
          <StateActionValueCard playerId={playerId} filters={filters} />
        </RoleGuard>
      </ErrorBoundary>

      {/* ── Research Spine RS-3: ハザード・疲労モデル ── */}
      <ErrorBoundary>
        <RoleGuard
          allowedRoles={['analyst', 'coach']}
          fallback={<div className="bg-gray-800 rounded-lg p-6 text-center text-gray-500 text-sm">{t('analysis.restricted')}</div>}
        >
          <HazardFatigueCard playerId={playerId} filters={filters} />
        </RoleGuard>
      </ErrorBoundary>

      {/* ── Research Spine RS-3: 反事実的ショット v2 ── */}
      <ErrorBoundary>
        <RoleGuard
          allowedRoles={['analyst', 'coach']}
          fallback={<div className="bg-gray-800 rounded-lg p-6 text-center text-gray-500 text-sm">{t('analysis.restricted')}</div>}
        >
          <CounterfactualV2Card playerId={playerId} filters={filters} />
        </RoleGuard>
      </ErrorBoundary>
    </div>
  )
}
