// Tier / Evidence バッジコンポーネント
import { useIsLightMode } from '@/hooks/useIsLightMode'

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
  stable: 'bg-emerald-900/70 border-emerald-500 text-emerald-200',
  advanced: 'bg-blue-900/70 border-blue-500 text-blue-200',
  research: 'bg-amber-900/70 border-amber-500 text-amber-200',
}
const TIER_COLORS_LIGHT: Record<Tier, string> = {
  stable: 'bg-emerald-50 border-emerald-400 text-emerald-700',
  advanced: 'bg-blue-50 border-blue-400 text-blue-700',
  research: 'bg-amber-50 border-amber-400 text-amber-700',
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
        <span className={`text-[10px] ${warnText}`}>推奨非対応</span>
      )}
    </div>
  )
}
