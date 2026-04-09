// Tier / Evidence バッジコンポーネント
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

const TIER_COLORS: Record<Tier, string> = {
  stable: 'bg-emerald-900/50 border-emerald-600 text-emerald-300',
  advanced: 'bg-blue-900/50 border-blue-600 text-blue-300',
  research: 'bg-amber-900/50 border-amber-600 text-amber-300',
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
  return (
    <div className={`inline-flex flex-wrap items-center gap-1 ${className}`}>
      <span className={`inline-flex items-center px-1.5 py-0.5 rounded border text-[10px] font-medium ${TIER_COLORS[tier]}`}>
        {TIER_LABELS[tier]}
      </span>
      {evidenceLevel && (
        <span className="text-[10px] text-gray-500 border border-gray-700 rounded px-1.5 py-0.5">
          {EVIDENCE_LABELS[evidenceLevel]}
        </span>
      )}
      {sampleSize != null && (
        <span className="text-[10px] text-gray-600">N={sampleSize.toLocaleString()}</span>
      )}
      {confidenceLevel != null && (
        <span className="text-[10px] text-gray-600">{(confidenceLevel * 100).toFixed(0)}%</span>
      )}
      {recommendationAllowed === false && (
        <span className="text-[10px] text-amber-500">推奨非対応</span>
      )}
    </div>
  )
}
