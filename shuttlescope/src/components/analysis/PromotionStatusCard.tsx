import React, { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiPost, apiDelete } from '@/api/client'
import { useCardTheme } from '@/hooks/useCardTheme'
import { useAuth } from '@/hooks/useAuth'
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

interface OverrideEntry {
  analysis_type: string
  status: string
  note: string
  analyst: string
  updated_at: string
}

interface Props {
  playerId: number
  filters: AnalysisFilters
}

const TIER_LABELS: Record<string, string> = {
  research: 'Research',
  advanced: 'Advanced',
  stable: 'Stable',
}

const OVERRIDE_STATUS_OPTIONS = [
  { value: 'promotion_ready', label: '昇格準備完了' },
  { value: 'requires_review', label: 'レビュー待ち' },
  { value: 'insufficient_data', label: 'データ不足' },
  { value: 'hold', label: '保留（note必須）' },
]

interface ThemeProps {
  isLight: boolean
  textHeading: string
  textSecondary: string
  textMuted: string
  textFaint: string
  cardInner: string
  cardInnerAlt: string
  border: string
}

function getStatusConfig(isLight: boolean) {
  return {
    promotion_ready: {
      label: '昇格準備完了',
      color: isLight ? 'text-emerald-600' : 'text-emerald-400',
      dot: isLight ? 'bg-emerald-500' : 'bg-emerald-400',
    },
    requires_review: {
      label: 'レビュー待ち',
      color: isLight ? 'text-amber-600' : 'text-yellow-400',
      dot: isLight ? 'bg-amber-500' : 'bg-yellow-400',
    },
    insufficient_data: {
      label: 'データ不足',
      color: isLight ? 'text-gray-500' : 'text-gray-500',
      dot: isLight ? 'bg-gray-400' : 'bg-gray-600',
    },
    hold: {
      label: '保留',
      color: isLight ? 'text-orange-600' : 'text-orange-400',
      dot: isLight ? 'bg-orange-500' : 'bg-orange-400',
    },
  } as const
}

function getTierColors(isLight: boolean): Record<string, string> {
  return isLight ? {
    research: 'text-purple-700 border-purple-400',
    advanced: 'text-sky-700 border-sky-400',
    stable: 'text-emerald-700 border-emerald-400',
  } : {
    research: 'text-purple-400 border-purple-700',
    advanced: 'text-sky-400 border-sky-700',
    stable: 'text-emerald-400 border-emerald-700',
  }
}

function ChecklistBullet({ item, isLight }: { item: ChecklistItem; isLight: boolean }) {
  const icon = item.met === true ? '✓' : item.met === false ? '✗' : '○'
  const color =
    item.met === true ? (isLight ? 'text-emerald-600' : 'text-emerald-400') :
    item.met === false ? (isLight ? 'text-red-600' : 'text-red-400') :
    'text-gray-500'
  const textColor = isLight ? 'text-gray-600' : 'text-gray-400'
  const subColor = isLight ? 'text-gray-400' : 'text-gray-600'
  return (
    <li className="flex items-start gap-1.5 text-[10px]">
      <span className={`${color} shrink-0 font-bold mt-px`}>{icon}</span>
      <span className={textColor}>{item.item}</span>
      {item.current !== null && (
        <span className={`${subColor} ml-auto shrink-0`}>{item.current} / {item.required}</span>
      )}
    </li>
  )
}

function OverrideForm({
  analysisType,
  currentOverride,
  theme,
  onClose,
}: {
  analysisType: string
  currentOverride: OverrideEntry | undefined
  theme: ThemeProps
  onClose: () => void
}) {
  const { isLight, textHeading, textMuted, textFaint, cardInner, border } = theme
  const { role } = useAuth()
  const qc = useQueryClient()
  const [status, setStatus] = useState(currentOverride?.status ?? 'requires_review')
  const [note, setNote] = useState(currentOverride?.note ?? '')
  const [saving, setSaving] = useState(false)

  const inputClass = isLight
    ? 'bg-white border border-gray-300 text-gray-700 focus:ring-1 focus:ring-blue-400'
    : 'bg-gray-700 border border-gray-600 text-gray-200 focus:ring-1 focus:ring-blue-500'
  const btnPrimary = isLight
    ? 'bg-blue-600 hover:bg-blue-700 text-white'
    : 'bg-blue-500 hover:bg-blue-600 text-white'
  const btnDanger = isLight
    ? 'text-red-600 hover:text-red-700'
    : 'text-red-400 hover:text-red-300'

  const handleSave = async () => {
    setSaving(true)
    try {
      await apiPost('/analysis/meta/promotion_override', {
        analysis_type: analysisType,
        status,
        note,
        analyst: role ?? 'analyst',
      })
      await qc.invalidateQueries({ queryKey: ['promotion-overrides'] })
      onClose()
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    setSaving(true)
    try {
      await apiDelete(`/analysis/meta/promotion_override/${analysisType}`)
      await qc.invalidateQueries({ queryKey: ['promotion-overrides'] })
      onClose()
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className={`mt-2 p-2 rounded border ${border} ${cardInner} space-y-2`}>
      <p className={`text-[10px] font-semibold ${textHeading}`}>アナリスト判断 Override</p>
      <select
        className={`w-full text-xs rounded px-2 py-1 ${inputClass}`}
        value={status}
        onChange={(e) => setStatus(e.target.value)}
      >
        {OVERRIDE_STATUS_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
      <textarea
        className={`w-full text-xs rounded px-2 py-1 resize-none ${inputClass}`}
        rows={2}
        placeholder="判断の根拠・保留理由など（任意）"
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />
      <div className="flex items-center gap-2 justify-end">
        {currentOverride && (
          <button
            className={`text-[10px] ${btnDanger} transition-colors`}
            onClick={handleDelete}
            disabled={saving}
          >
            削除
          </button>
        )}
        <button
          className={`text-[10px] ${textMuted} hover:${textHeading}`}
          onClick={onClose}
          disabled={saving}
        >
          キャンセル
        </button>
        <button
          className={`text-[10px] px-2 py-0.5 rounded ${btnPrimary} transition-colors`}
          onClick={handleSave}
          disabled={saving}
        >
          {saving ? '保存中…' : '保存'}
        </button>
      </div>
    </div>
  )
}

function EvaluationRow({
  entry,
  override,
  isAnalyst,
  theme,
}: {
  entry: EvaluationEntry
  override: OverrideEntry | undefined
  isAnalyst: boolean
  theme: ThemeProps
}) {
  const { isLight, textHeading, textMuted, textFaint, border } = theme
  const statusConfig = getStatusConfig(isLight)
  const tierColors = getTierColors(isLight)
  const [expanded, setExpanded] = useState(false)
  const [showOverride, setShowOverride] = useState(false)
  const hoverBg = isLight ? 'hover:bg-gray-50' : 'hover:bg-gray-700/30'
  const expandedBorder = isLight ? 'border-t border-gray-100' : 'border-t border-gray-700'

  // Override が存在する場合は override のステータスを優先表示
  const effectiveStatus = override?.status ?? entry.status
  const statusCfg = statusConfig[effectiveStatus as keyof typeof statusConfig] ?? statusConfig.requires_review

  return (
    <div className={`border ${border} rounded-lg overflow-hidden`}>
      <button
        className={`w-full flex items-center gap-2 px-3 py-2 text-left ${hoverBg} transition-colors`}
        onClick={() => setExpanded((v) => !v)}
      >
        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${statusCfg.dot}`} />
        <span className={`text-xs flex-1 text-left ${textHeading}`}>{entry.analysis_type}</span>
        {override && (
          <span className={`text-[9px] px-1 py-0.5 rounded ${isLight ? 'bg-blue-50 text-blue-600 border border-blue-200' : 'bg-blue-900/40 text-blue-400 border border-blue-700'}`}>
            Override
          </span>
        )}
        <span className={`text-[9px] border rounded px-1 py-0.5 shrink-0 ${tierColors[entry.from_tier] ?? (isLight ? 'text-gray-500 border-gray-300' : 'text-gray-500 border-gray-600')}`}>
          {TIER_LABELS[entry.from_tier] ?? entry.from_tier}
        </span>
        <span className={`text-[10px] ${textFaint}`}>→</span>
        <span className={`text-[9px] border rounded px-1 py-0.5 shrink-0 ${tierColors[entry.to_tier] ?? (isLight ? 'text-gray-500 border-gray-300' : 'text-gray-500 border-gray-600')}`}>
          {TIER_LABELS[entry.to_tier] ?? entry.to_tier}
        </span>
        <span className={`text-[10px] font-medium shrink-0 ${statusCfg.color}`}>{statusCfg.label}</span>
        <span className={`text-[10px] shrink-0 ${textFaint}`}>{expanded ? '▲' : '▼'}</span>
      </button>

      {expanded && (
        <div className={`px-3 pb-3 pt-1 ${expandedBorder} space-y-2`}>
          <div className={`flex items-center gap-2 text-[10px] ${textMuted}`}>
            <span>サンプル: {entry.sample_count}</span>
            <span>チェック: {entry.met_count}/{entry.total_count}</span>
          </div>
          <ul className="space-y-0.5">
            {entry.checklist.map((item, i) => (
              <ChecklistBullet key={i} item={item} isLight={isLight} />
            ))}
          </ul>
          {entry.additional_notes && (
            <p className={`text-[10px] italic ${textFaint}`}>{entry.additional_notes}</p>
          )}
          {override && (
            <div className={`text-[10px] space-y-0.5 ${isLight ? 'text-blue-700' : 'text-blue-400'}`}>
              <p className="font-medium">Override 設定済み: {override.status}</p>
              {override.note && <p className={textMuted}>{override.note}</p>}
              <p className={textFaint}>{override.updated_at}</p>
            </div>
          )}
          {isAnalyst && (
            <>
              <button
                className={`text-[10px] underline ${isLight ? 'text-gray-500 hover:text-gray-700' : 'text-gray-500 hover:text-gray-300'}`}
                onClick={() => setShowOverride((v) => !v)}
              >
                {showOverride ? 'Override フォームを閉じる' : (override ? 'Override を編集' : '+ Override を追加')}
              </button>
              {showOverride && (
                <OverrideForm
                  analysisType={entry.analysis_type}
                  currentOverride={override}
                  theme={theme}
                  onClose={() => setShowOverride(false)}
                />
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}

export function PromotionStatusCard({ playerId, filters }: Props) {
  const { card, cardInner, cardInnerAlt, textHeading, textSecondary, textMuted, textFaint, border, loading, badge, isLight } = useCardTheme()
  const { role } = useAuth()
  const isAnalyst = role === 'analyst'
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

  const { data: overridesResp } = useQuery({
    queryKey: ['promotion-overrides'],
    queryFn: () => apiGet<{ success: boolean; data: Record<string, OverrideEntry> }>('/analysis/meta/promotion_overrides'),
    staleTime: 30 * 1000,
  })

  const evalData = data?.data
  const summary = evalData?.summary
  const evaluations = evalData?.evaluations ?? []
  const demotionConditions = evalData?.demotion_conditions
  const overrides = overridesResp?.data ?? {}
  const theme: ThemeProps = { isLight, textHeading, textSecondary, textMuted, textFaint, cardInner, cardInnerAlt, border }

  return (
    <div className={`${card} rounded-lg p-4 space-y-3`}>
      <div className="flex items-center justify-between">
        <h3 className={`text-sm font-semibold ${textHeading}`}>昇格ワークフロー（Promotion Workflow）</h3>
        <span className={`text-[9px] rounded px-1.5 py-0.5 ${badge}`}>analyst/coach</span>
      </div>

      <p className={`text-[10px] ${textMuted}`}>
        各 research/advanced 指標の昇格基準に対する現在の達成状況を示します。
        {isAnalyst && ' アナリストは Override で手動判断を記録できます。'}
      </p>

      {isLoading ? (
        <p className={`text-sm text-center py-4 ${loading}`}>評価中...</p>
      ) : (
        <div className="space-y-3">
          {/* サマリー */}
          {summary && (
            <div className="grid grid-cols-3 gap-2">
              <div className={`${cardInner} rounded px-2 py-1.5 text-center`}>
                <div className={`text-sm font-bold ${isLight ? 'text-emerald-600' : 'text-emerald-400'}`}>{summary.promotion_ready_count}</div>
                <div className={`text-[10px] ${textMuted}`}>昇格準備完了</div>
              </div>
              <div className={`${cardInner} rounded px-2 py-1.5 text-center`}>
                <div className={`text-sm font-bold ${isLight ? 'text-amber-600' : 'text-yellow-400'}`}>{summary.requires_review_count}</div>
                <div className={`text-[10px] ${textMuted}`}>レビュー待ち</div>
              </div>
              <div className={`${cardInner} rounded px-2 py-1.5 text-center`}>
                <div className={`text-sm font-bold ${textSecondary}`}>{summary.insufficient_data_count}</div>
                <div className={`text-[10px] ${textMuted}`}>データ不足</div>
              </div>
            </div>
          )}

          <div className={`text-[10px] ${textFaint}`}>
            {summary && <>ラリー: {summary.n_rallies} / 試合: {summary.n_matches} / 対戦相手: {summary.n_opponents}</>}
          </div>

          {/* 評価リスト */}
          <div className="space-y-1.5">
            {evaluations.map((entry) => (
              <EvaluationRow
                key={`${entry.analysis_type}-${entry.from_tier}`}
                entry={entry}
                override={overrides[entry.analysis_type]}
                isAnalyst={isAnalyst}
                theme={theme}
              />
            ))}
          </div>

          {/* 降格条件 */}
          {demotionConditions && (
            <div>
              <button
                className={`text-[10px] underline ${isLight ? 'text-gray-500 hover:text-gray-700' : 'text-gray-500 hover:text-gray-400'}`}
                onClick={() => setShowDemotion((v) => !v)}
              >
                {showDemotion ? '降格条件を隠す ▲' : '降格条件を表示 ▼'}
              </button>
              {showDemotion && (
                <div className="mt-2 space-y-2">
                  <div className={`${cardInner} rounded px-2 py-2`}>
                    <p className={`text-[10px] font-medium mb-1 ${textSecondary}`}>共通降格条件</p>
                    <ul className="space-y-0.5">
                      {(demotionConditions.general ?? []).map((cond, i) => (
                        <li key={i} className={`text-[10px] flex items-start gap-1 ${textMuted}`}>
                          <span className={`shrink-0 ${isLight ? 'text-orange-600' : 'text-orange-400'}`}>•</span>
                          {cond}
                        </li>
                      ))}
                    </ul>
                  </div>
                  {Object.entries(demotionConditions)
                    .filter(([k]) => k !== 'general')
                    .map(([type, conds]) => (
                      <div key={type} className={`${cardInnerAlt} rounded px-2 py-1.5`}>
                        <p className={`text-[10px] font-medium mb-0.5 ${textMuted}`}>{type}</p>
                        <ul>
                          {conds.map((c, i) => (
                            <li key={i} className={`text-[10px] ${textFaint}`}>• {c}</li>
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
