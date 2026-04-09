import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'
import { AnalysisFilters } from '@/types'

interface ChecklistItem {
  item: string
  met: boolean | null
  current: number | string | null
  required: number | string | null
}

interface EvaluationEntry {
  analysis_type: string
  from_tier: string
  to_tier: string
  current_tier: string
  sample_count: number
  status: 'promotion_ready' | 'requires_review' | 'insufficient_data'
  checklist: ChecklistItem[]
  met_count: number
  total_count: number
  additional_notes: string
}

interface DemotionConditions {
  general: string[]
  [key: string]: string[]
}

interface EvaluationData {
  evaluations: EvaluationEntry[]
  summary: {
    n_rallies: number
    n_matches: number
    n_opponents: number
    n_doubles_matches: number
    promotion_ready_count: number
    requires_review_count: number
    insufficient_data_count: number
  }
  demotion_conditions: DemotionConditions
}

interface Props {
  playerId: number
  filters: AnalysisFilters
}

const STATUS_CONFIG = {
  promotion_ready: { label: '昇格準備完了', color: 'text-emerald-400', dot: 'bg-emerald-400' },
  requires_review: { label: 'レビュー待ち', color: 'text-yellow-400', dot: 'bg-yellow-400' },
  insufficient_data: { label: 'データ不足', color: 'text-gray-500', dot: 'bg-gray-600' },
} as const

const TIER_LABELS: Record<string, string> = {
  research: 'Research',
  advanced: 'Advanced',
  stable: 'Stable',
}

const TIER_COLORS: Record<string, string> = {
  research: 'text-purple-400 border-purple-700',
  advanced: 'text-sky-400 border-sky-700',
  stable: 'text-emerald-400 border-emerald-700',
}

function ChecklistBullet({ item }: { item: ChecklistItem }) {
  const icon =
    item.met === true ? '✓' :
    item.met === false ? '✗' : '○'
  const color =
    item.met === true ? 'text-emerald-400' :
    item.met === false ? 'text-red-400' : 'text-gray-500'
  return (
    <li className="flex items-start gap-1.5 text-[10px]">
      <span className={`${color} shrink-0 font-bold mt-px`}>{icon}</span>
      <span className="text-gray-400">{item.item}</span>
      {item.current !== null && (
        <span className="text-gray-600 ml-auto shrink-0">
          {item.current} / {item.required}
        </span>
      )}
    </li>
  )
}

function EvaluationRow({ entry }: { entry: EvaluationEntry }) {
  const status = STATUS_CONFIG[entry.status]
  const [expanded, setExpanded] = React.useState(false)

  return (
    <div className="border border-gray-700 rounded-lg overflow-hidden">
      <button
        className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-gray-700/30 transition-colors"
        onClick={() => setExpanded((v) => !v)}
      >
        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${status.dot}`} />
        <span className="text-xs text-white flex-1 text-left">{entry.analysis_type}</span>
        <span className={`text-[9px] border rounded px-1 py-0.5 shrink-0 ${TIER_COLORS[entry.from_tier] ?? 'text-gray-500 border-gray-600'}`}>
          {TIER_LABELS[entry.from_tier] ?? entry.from_tier}
        </span>
        <span className="text-gray-600 text-[10px]">→</span>
        <span className={`text-[9px] border rounded px-1 py-0.5 shrink-0 ${TIER_COLORS[entry.to_tier] ?? 'text-gray-500 border-gray-600'}`}>
          {TIER_LABELS[entry.to_tier] ?? entry.to_tier}
        </span>
        <span className={`text-[10px] font-medium shrink-0 ${status.color}`}>{status.label}</span>
        <span className="text-gray-600 text-[10px] shrink-0">{expanded ? '▲' : '▼'}</span>
      </button>
      {expanded && (
        <div className="px-3 pb-3 pt-1 border-t border-gray-700 space-y-2">
          <div className="flex items-center gap-2 text-[10px] text-gray-500">
            <span>サンプル: {entry.sample_count}</span>
            <span>チェック: {entry.met_count}/{entry.total_count}</span>
          </div>
          <ul className="space-y-0.5">
            {entry.checklist.map((item, i) => (
              <ChecklistBullet key={i} item={item} />
            ))}
          </ul>
          {entry.additional_notes && (
            <p className="text-[10px] text-gray-600 italic">{entry.additional_notes}</p>
          )}
        </div>
      )}
    </div>
  )
}

// React をインポート (useQuery が require するため)
import React, { useState } from 'react'

export function PromotionStatusCard({ playerId, filters }: Props) {
  const [showDemotion, setShowDemotion] = useState(false)

  const filterApiParams = {
    ...(filters.result !== 'all' ? { result: filters.result } : {}),
    ...(filters.tournamentLevel ? { tournament_level: filters.tournamentLevel } : {}),
    ...(filters.dateFrom ? { date_from: filters.dateFrom } : {}),
    ...(filters.dateTo ? { date_to: filters.dateTo } : {}),
  }

  const { data, isLoading } = useQuery({
    queryKey: ['promotion-evaluation', playerId, filters],
    queryFn: () =>
      apiGet<{ success: boolean; data: EvaluationData }>(
        '/analysis/meta/promotion_evaluation',
        { player_id: playerId, ...filterApiParams }
      ),
    staleTime: 5 * 60 * 1000,
  })

  const evalData = data?.data
  const summary = evalData?.summary
  const evaluations = evalData?.evaluations ?? []
  const demotionConditions = evalData?.demotion_conditions

  return (
    <div className="bg-gray-800 rounded-lg p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-200">昇格ワークフロー（Promotion Workflow）</h3>
        <span className="text-[9px] text-gray-500 border border-gray-600 rounded px-1.5 py-0.5">analyst/coach</span>
      </div>

      <p className="text-[10px] text-gray-500">
        各 research/advanced 指標の昇格基準に対する現在の達成状況を示します。
        サンプル数以外の条件（校正・コーチテスト）はアナリストが手動で確認してください。
      </p>

      {isLoading ? (
        <p className="text-gray-500 text-sm text-center py-4">評価中...</p>
      ) : (
        <div className="space-y-3">
          {/* サマリー */}
          {summary && (
            <div className="grid grid-cols-3 gap-2">
              <div className="bg-gray-700/40 rounded px-2 py-1.5 text-center">
                <div className="text-emerald-400 text-sm font-bold">{summary.promotion_ready_count}</div>
                <div className="text-[10px] text-gray-500">昇格準備完了</div>
              </div>
              <div className="bg-gray-700/40 rounded px-2 py-1.5 text-center">
                <div className="text-yellow-400 text-sm font-bold">{summary.requires_review_count}</div>
                <div className="text-[10px] text-gray-500">レビュー待ち</div>
              </div>
              <div className="bg-gray-700/40 rounded px-2 py-1.5 text-center">
                <div className="text-gray-400 text-sm font-bold">{summary.insufficient_data_count}</div>
                <div className="text-[10px] text-gray-500">データ不足</div>
              </div>
            </div>
          )}

          <div className="text-[10px] text-gray-600">
            {summary && (
              <>ラリー: {summary.n_rallies} / 試合: {summary.n_matches} / 対戦相手: {summary.n_opponents}</>
            )}
          </div>

          {/* 評価リスト */}
          <div className="space-y-1.5">
            {evaluations.map((entry) => (
              <EvaluationRow key={`${entry.analysis_type}-${entry.from_tier}`} entry={entry} />
            ))}
          </div>

          {/* 降格条件 */}
          {demotionConditions && (
            <div>
              <button
                className="text-[10px] text-gray-500 hover:text-gray-400 underline"
                onClick={() => setShowDemotion((v) => !v)}
              >
                {showDemotion ? '降格条件を隠す ▲' : '降格条件を表示 ▼'}
              </button>
              {showDemotion && (
                <div className="mt-2 space-y-2">
                  <div className="bg-gray-700/30 rounded px-2 py-2">
                    <p className="text-[10px] text-gray-400 font-medium mb-1">共通降格条件</p>
                    <ul className="space-y-0.5">
                      {(demotionConditions.general ?? []).map((cond, i) => (
                        <li key={i} className="text-[10px] text-gray-500 flex items-start gap-1">
                          <span className="text-orange-400 shrink-0">•</span>
                          {cond}
                        </li>
                      ))}
                    </ul>
                  </div>
                  {Object.entries(demotionConditions)
                    .filter(([k]) => k !== 'general')
                    .map(([type, conds]) => (
                      <div key={type} className="bg-gray-700/20 rounded px-2 py-1.5">
                        <p className="text-[10px] text-gray-500 font-medium mb-0.5">{type}</p>
                        <ul>
                          {conds.map((c, i) => (
                            <li key={i} className="text-[10px] text-gray-600">• {c}</li>
                          ))}
                        </ul>
                      </div>
                    ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
