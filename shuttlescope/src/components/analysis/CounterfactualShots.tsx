// 反事実的ショット比較 — 同じ文脈での返球選択肢比較（アナリスト・コーチのみ）
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { NoDataMessage } from '@/components/common/NoDataMessage'
import { RoleGuard } from '@/components/common/RoleGuard'
import { perfColor, WIN } from '@/styles/colors'

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
  lift: number
  interpretation: string
}

interface Response {
  success: boolean
  data: { comparisons: Comparison[] }
  meta: { sample_size: number; confidence: { level: string; stars: string; label: string } }
}

function ChoiceBar({ choice, recommended }: { choice: ShotChoice; recommended: string }) {
  const isRec = choice.shot_type === recommended
  const pct = Math.round(choice.win_rate * 100)
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className={`w-24 text-right truncate shrink-0 ${isRec ? 'text-white font-medium' : 'text-gray-400'}`}>
        {choice.label}
      </span>
      <div className="flex-1 bg-gray-700 rounded h-4 relative overflow-hidden">
        <div
          className="h-full rounded transition-all"
          style={{ width: `${pct}%`, backgroundColor: perfColor(choice.win_rate) }}
        />
        <span className="absolute inset-0 flex items-center justify-center text-white text-xs font-mono">
          {pct}%
        </span>
      </div>
      <span className="text-gray-500 text-xs w-8 text-right">{choice.count}</span>
      {isRec && (
        <span
          className="text-xs px-1.5 py-0.5 rounded font-semibold shrink-0"
          style={{ backgroundColor: WIN, color: 'white' }}
        >
          推奨
        </span>
      )}
    </div>
  )
}

function ComparisonAccordion({ comp }: { comp: Comparison }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="border border-gray-700 rounded-lg overflow-hidden">
      <button
        className="w-full flex items-center justify-between px-3 py-2 text-left hover:bg-gray-700/50 transition-colors"
        onClick={() => setOpen(v => !v)}
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-sm text-gray-200 truncate">{comp.context_label}</span>
          <span
            className="text-xs px-1.5 py-0.5 rounded shrink-0"
            style={{ backgroundColor: WIN + '33', color: WIN, border: `1px solid ${WIN}` }}
          >
            lift +{Math.round(comp.lift * 100)}%
          </span>
        </div>
        <span className="text-gray-400 ml-2">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="px-3 pb-3 space-y-2 border-t border-gray-700 pt-2">
          <div className="space-y-1.5">
            {comp.choices.map(c => (
              <ChoiceBar key={c.shot_type} choice={c} recommended={comp.recommended} />
            ))}
          </div>
          <p className="text-xs text-gray-400 mt-2 italic">{comp.interpretation}</p>
        </div>
      )}
    </div>
  )
}

function Inner({ playerId }: { playerId: number }) {
  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-counterfactual-shots', playerId],
    queryFn: () => apiGet<Response>('/analysis/counterfactual_shots', { player_id: playerId }),
    enabled: !!playerId,
  })

  if (isLoading) {
    return <div className="text-gray-500 text-sm py-4 text-center">読み込み中...</div>
  }

  const comparisons = resp?.data?.comparisons ?? []
  const sampleSize = resp?.meta?.sample_size ?? 0

  if (comparisons.length === 0) {
    return <NoDataMessage sampleSize={sampleSize} minRequired={30} unit="ラリー" />
  }

  return (
    <div className="space-y-3">
      <ConfidenceBadge sampleSize={sampleSize} />
      <p className="text-xs text-gray-400">各状況でどの返球が最も効果的かを比較します</p>
      <div className="space-y-2">
        {comparisons.map((c, i) => (
          <ComparisonAccordion key={i} comp={c} />
        ))}
      </div>
    </div>
  )
}

export function CounterfactualShots({ playerId }: CounterfactualShotsProps) {
  return (
    <RoleGuard allowedRoles={['analyst', 'coach']}>
      <div className="bg-gray-800 rounded-lg p-4">
        <h3 className="text-sm font-semibold text-gray-200 mb-3">反事実的ショット比較</h3>
        <Inner playerId={playerId} />
      </div>
    </RoleGuard>
  )
}
