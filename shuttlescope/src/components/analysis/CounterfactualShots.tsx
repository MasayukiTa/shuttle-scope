// 反事実的ショット比較 — 同じ文脈での返球選択肢比較（アナリスト・コーチのみ）
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'
import { useResearchBundleSlice } from '@/contexts/ResearchBundleContext'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { NoDataMessage } from '@/components/common/NoDataMessage'
import { RoleGuard } from '@/components/common/RoleGuard'
import { perfColor, WIN } from '@/styles/colors'
import { useTranslation } from 'react-i18next'

interface CounterfactualShotsProps {
  playerId: number
}

interface ShotChoice {
  shot_type: string
  label: string
  count: number
  win_rate: number
}

interface Comparison {
  context_label: string
  prev_shot: string
  choices: ShotChoice[]
  recommended: string
  // 1位と2位の 95% 区間が離れているときだけ true。無いときは過去実績の並びに留める
  recommendation_supported?: boolean
  lift: number
  interpretation: string
}

interface Response {
  success: boolean
  data: { comparisons: Comparison[] }
  meta: { sample_size: number; confidence: { level: string; stars: string; label: string } }
}

function ChoiceBar({ choice, recommended }: { choice: ShotChoice; recommended: string }) {
  const { t } = useTranslation()

  const isRec = choice.shot_type === recommended
  const pct = Math.round(choice.win_rate * 100)
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className={`w-24 text-right truncate shrink-0 ${isRec ? 'text-white font-medium' : 'text-gray-400'}`}>
        {choice.label}
      </span>
      <div className="flex-1 bg-gray-700 rounded-ss-sm h-4 relative overflow-hidden">
        <div
          className="h-full rounded-ss-sm transition-all duration-base ease-out"
          style={{ width: `${pct}%`, backgroundColor: perfColor(choice.win_rate) }}
        />
        <span className="absolute inset-0 flex items-center justify-center text-white text-xs font-mono ss-num">
          {pct}%
        </span>
      </div>
      <span className="text-gray-500 text-xs w-8 text-right ss-num">{choice.count}</span>
      {isRec && (
        <span
          className="text-xs px-1.5 py-0.5 rounded-ss-sm font-semibold shrink-0"
          style={{ backgroundColor: WIN, color: 'white' }}
        >
          {t('auto.CounterfactualShots.recommended')}
        </span>
      )}
    </div>
  )
}

// 縮退検出: 代替ショットの勝率が 100%（または 0%）に張り付いている、
// あるいは全候補が同一勝率で差が付いていないとき、観察率は信頼できない
// (完全分離 / ターゲットリーク / 標本過少)。この場合「改善幅」として見せない。
function isDegenerate(comp: Comparison): boolean {
  const choices = comp.choices
  if (choices.length < 2) return true
  const top = choices[0]
  // 1位の勝率が境界値 (100% / 0%) に張り付いている
  if (top.win_rate >= 1 || top.win_rate <= 0) return true
  // 全候補の勝率が同一 (差分 0) に縮退している
  const allSame = choices.every(c => c.win_rate === top.win_rate)
  if (allSame) return true
  return false
}

function ComparisonAccordion({ comp }: { comp: Comparison }) {
  const { t } = useTranslation()

  const degenerate = isDegenerate(comp)
  const showLift = comp.recommendation_supported && !degenerate
  const [open, setOpen] = useState(false)
  return (
    <div className="border border-gray-700 rounded-ss-lg overflow-hidden">
      <button
        className="w-full flex items-center justify-between px-3 py-2 text-left hover:bg-gray-700/50 transition-colors duration-fast"
        onClick={() => setOpen(v => !v)}
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-sm text-gray-200 truncate">{comp.context_label}</span>
          {degenerate ? (
            <span
              className="text-xs px-1.5 py-0.5 rounded-ss-sm shrink-0"
              style={{ backgroundColor: '#78350f', color: '#fbbf24', border: '1px solid #f59e0b' }}
            >
              {t('auto.CounterfactualShots.degenerate_badge')}
            </span>
          ) : (
            <span
              className="text-xs px-1.5 py-0.5 rounded-ss-sm shrink-0 ss-num"
              style={{ backgroundColor: WIN + '33', color: WIN, border: `1px solid ${WIN}` }}
            >
              {showLift ? t('auto.CounterfactualShots.lift', { n: Math.round(comp.lift * 100) }) : t('auto.CounterfactualShots.observed_only')}
            </span>
          )}
        </div>
        <span className="text-gray-400 ml-2">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="px-3 pb-3 space-y-2 border-t border-gray-700 pt-2">
          <div className="space-y-1.5">
            {comp.choices.map(c => (
              <ChoiceBar key={c.shot_type} choice={c} recommended={showLift ? comp.recommended : ''} />
            ))}
          </div>
          {degenerate && (
            <p className="text-xs mt-2" style={{ color: '#fbbf24' }}>
              {t('auto.CounterfactualShots.degenerate_warning')}
            </p>
          )}
          <p className="text-xs text-gray-400 mt-2 italic">{comp.interpretation}</p>
        </div>
      )}
    </div>
  )
}

function Inner({ playerId }: { playerId: number }) {
  const { t } = useTranslation()

  const { slice: bundled, loading: bundleLoading, provided } = useResearchBundleSlice<Response>('counterfactual_shots')
  const indiv = useQuery({
    queryKey: ['analysis-counterfactual-shots', playerId],
    queryFn: () => apiGet<Response>('/analysis/counterfactual_shots', { player_id: playerId }),
    enabled: !!playerId && !provided && !bundleLoading,
  })
  const resp = bundled ?? indiv.data
  const isLoading = provided ? bundleLoading : indiv.isLoading

  if (isLoading) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('auto.CounterfactualShots.k1')}</div>
  }

  const comparisons = resp?.data?.comparisons ?? []
  const sampleSize = resp?.meta?.sample_size ?? 0

  if (comparisons.length === 0) {
    return <NoDataMessage sampleSize={sampleSize} minRequired={30} unit="ストローク" />
  }

  return (
    <div className="space-y-3">
      <ConfidenceBadge sampleSize={sampleSize} tier="research" unit="strokes" />
      <p className="text-xs text-gray-400">{t('auto.CounterfactualShots.k2')}</p>
      <div className="space-y-2">
        {comparisons.map((c, i) => (
          <ComparisonAccordion key={i} comp={c} />
        ))}
      </div>
    </div>
  )
}

export function CounterfactualShots({ playerId }: CounterfactualShotsProps) {
  const { t } = useTranslation()

  return (
    <RoleGuard allowedRoles={['analyst', 'coach']}>
      <div className="bg-gray-800 rounded-ss-lg shadow-card p-4">
        <h3 className="text-sm font-semibold text-gray-200 mb-3">{t('auto.CounterfactualShots.k3')}</h3>
        <Inner playerId={playerId} />
      </div>
    </RoleGuard>
  )
}
