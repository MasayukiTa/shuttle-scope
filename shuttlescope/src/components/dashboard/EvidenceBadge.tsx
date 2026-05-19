// Tier / Evidence バッジコンポーネント
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { useTranslation } from 'react-i18next'

export type Tier = 'stable' | 'advanced' | 'research'
export type EvidenceLevel = 'exploratory' | 'directional' | 'practical_candidate' | 'practical_adopted'

interface EvidenceBadgeProps {
  tier: Tier
  evidenceLevel?: EvidenceLevel
  sampleSize?: number
  confidenceLevel?: number
  recommendationAllowed?: boolean
  className?: string
}

const TIER_LABELS: Record<Tier, string> = {
  stable: '安定',
  advanced: '詳細',
  research: '研究',
}

const TIER_COLORS_DARK: Record<Tier, string> = {
  stable: 'bg-gray-800 border-gray-700 text-blue-300',
  advanced: 'bg-gray-800 border-gray-700 text-blue-300',
  research: 'bg-gray-800 border-gray-700 text-amber-400',
}
const TIER_COLORS_LIGHT: Record<Tier, string> = {
  stable: 'bg-white border-gray-200 text-blue-700',
  advanced: 'bg-white border-gray-200 text-blue-700',
  research: 'bg-white border-gray-200 text-amber-700',
}

const EVIDENCE_LABELS: Record<EvidenceLevel, string> = {
  exploratory: '探索的',
  directional: '方向性あり',
  practical_candidate: '実用候補',
  practical_adopted: '実用採用',
}

export function EvidenceBadge({
  tier,
  evidenceLevel,
  sampleSize,
  confidenceLevel,
  recommendationAllowed,
  className = '',
}: EvidenceBadgeProps) {
  const { t } = useTranslation()

  const isLight = useIsLightMode()
  const tierColors = isLight ? TIER_COLORS_LIGHT : TIER_COLORS_DARK
  const metaText = isLight ? 'text-gray-500 border border-gray-300' : 'text-gray-300 border border-gray-600'
  const sampleText = isLight ? 'text-gray-500' : 'text-gray-400'
  const warnText = isLight ? 'text-amber-600' : 'text-amber-500'

  return (
    <div className={`inline-flex flex-wrap items-center gap-1 ${className}`}>
      <span className={`inline-flex items-center px-1.5 py-0.5 rounded border text-[10px] font-medium ${tierColors[tier]}`}>
        {TIER_LABELS[tier]}
      </span>
      {evidenceLevel && (
        <span className={`text-[10px] rounded px-1.5 py-0.5 ${metaText}`}>
          {EVIDENCE_LABELS[evidenceLevel]}
        </span>
      )}
      {sampleSize != null && (
        <span className={`text-[10px] ${sampleText}`}>N={sampleSize.toLocaleString()}</span>
      )}
      {confidenceLevel != null && (
        <span className={`text-[10px] ${sampleText}`}>{(confidenceLevel * 100).toFixed(0)}%</span>
      )}
      {recommendationAllowed === false && (
        <span className={`text-[10px] ${warnText}`}>{t('auto.EvidenceBadge.k1')}</span>
      )}
    </div>
  )
}
