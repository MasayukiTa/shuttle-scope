/**
 * ReviewQueuePanel — CV補助アノテーションのレビューキューパネル
 *
 * 表示内容:
 *   - 要確認ラリーの一覧（pending / completed 分離）
 *   - 理由コード（データ不足 vs 品質問題 カテゴリ別）
 *   - ラリー信頼度サマリー（candidatesData から lookup）
 *   - レビュー完了マーク
 *   - ラリーへのジャンプコールバック
 */
import { useState } from 'react'
import { clsx } from 'clsx'
import { AlertTriangle, CheckCircle, ClipboardList, RefreshCw, ChevronDown, ChevronRight } from 'lucide-react'
import type { ReviewQueueItem, CVCandidatesData } from '@/types/cv'

interface Props {
  items: ReviewQueueItem[]
  loading: boolean
  onMarkCompleted: (rallyId: number) => void
  /** candidatesData があれば信頼度サマリーを表示 */
  candidatesData?: CVCandidatesData | null
  /** ラリーにジャンプする（省略可） */
  onJumpToRally?: (rallyId: number, rallyNum: number) => void
  className?: string
}

const REASON_LABELS: Record<string, string> = {
  low_frame_coverage:     'フレーム不足',
  alignment_missing:      'アライメントなし',
  landing_zone_ambiguous: '着地ゾーン不明確',
  hitter_undetected:      '打者不明',
  multiple_near_players:  '打者候補競合',
  role_state_unstable:    'ロール不安定',
}

const DATA_REASONS = new Set(['low_frame_coverage', 'alignment_missing'])
const QUALITY_REASONS = new Set(['landing_zone_ambiguous', 'hitter_undetected', 'multiple_near_players', 'role_state_unstable'])

function groupReasons(codes: string[]): { data: string[]; quality: string[]; other: string[] } {
  const data: string[] = []
  const quality: string[] = []
  const other: string[] = []
  for (const c of codes) {
    if (DATA_REASONS.has(c)) data.push(c)
    else if (QUALITY_REASONS.has(c)) quality.push(c)
    else other.push(c)
  }
  return { data, quality, other }
}

function ConfidencePill({ value, label }: { value: number; label: string }) {
  const pct = Math.round(value * 100)
  return (
    <span
      className={clsx(
        'text-[9px] font-mono tabular-nums px-1 rounded',
        pct >= 70 ? 'bg-emerald-900/40 text-emerald-300' :
        pct >= 45 ? 'bg-blue-900/40 text-blue-300' : 'bg-amber-900/40 text-amber-300'
      )}
      title={`${label}: ${pct}%`}
    >
      {label} {pct}%
    </span>
  )
}

function QueueItem({
  item,
  candidatesData,
  onMarkCompleted,
  onJumpToRally,
}: {
  item: ReviewQueueItem
  candidatesData?: CVCandidatesData | null
  onMarkCompleted: (id: number) => void
  onJumpToRally?: (id: number, num: number) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const { data: dataReasons, quality: qualityReasons, other } = groupReasons(item.cv_reason_codes)
  const hasReasons = item.cv_reason_codes.length > 0
  const allReasonLabels = item.cv_reason_codes.map((c) => REASON_LABELS[c] ?? c)

  // candidatesData からラリーの信頼度サマリーを取得
  const rallyCandidate = candidatesData?.rallies?.[String(item.rally_id)]
  const summary = rallyCandidate?.cv_confidence_summary

  return (
    <div className="flex flex-col bg-amber-500/10 border border-amber-500/25 rounded px-2 py-1.5 gap-0.5">
      <div className="flex items-start gap-2">
        <AlertTriangle size={11} className="text-amber-400 mt-0.5 shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-xs font-semibold text-white">R{item.rally_num}</span>
            {/* 信頼度サマリー（利用可能な場合） */}
            {summary && (
              <>
                <ConfidencePill value={summary.land_zone_fill_rate} label="着地" />
                <ConfidencePill value={summary.hitter_fill_rate} label="打者" />
              </>
            )}
          </div>
          {/* 理由コード（折りたたみ可） */}
          {hasReasons && (
            <button
              onClick={() => setExpanded((v) => !v)}
              className="flex items-center gap-0.5 text-[9px] text-amber-400/70 hover:text-amber-400 mt-0.5"
            >
              {expanded ? <ChevronDown size={9} /> : <ChevronRight size={9} />}
              {allReasonLabels.join(' / ')}
            </button>
          )}
          {expanded && (
            <div className="mt-0.5 flex flex-col gap-0.5 pl-2">
              {dataReasons.length > 0 && (
                <div className="text-[9px] text-amber-300/70">
                  <span className="text-slate-500 mr-1">データ:</span>
                  {dataReasons.map((c) => REASON_LABELS[c] ?? c).join(' · ')}
                </div>
              )}
              {qualityReasons.length > 0 && (
                <div className="text-[9px] text-amber-300/70">
                  <span className="text-slate-500 mr-1">品質:</span>
                  {qualityReasons.map((c) => REASON_LABELS[c] ?? c).join(' · ')}
                </div>
              )}
              {other.length > 0 && (
                <div className="text-[9px] text-slate-500">
                  {other.map((c) => REASON_LABELS[c] ?? c).join(' · ')}
                </div>
              )}
            </div>
          )}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {onJumpToRally && (
            <button
              onClick={() => onJumpToRally(item.rally_id, item.rally_num)}
              className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/20 hover:bg-blue-500/40 text-blue-300 transition-colors"
              title="このラリーに移動"
            >
              移動
            </button>
          )}
          <button
            onClick={() => onMarkCompleted(item.rally_id)}
            className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/20 hover:bg-emerald-500/40 text-emerald-300 transition-colors"
            title="レビュー完了としてマーク"
          >
            完了
          </button>
        </div>
      </div>
    </div>
  )
}

export function ReviewQueuePanel({
  items,
  loading,
  onMarkCompleted,
  candidatesData,
  onJumpToRally,
  className,
}: Props) {
  const [showCompleted, setShowCompleted] = useState(false)
  const pending = items.filter((i) => i.review_status !== 'completed')
  const completed = items.filter((i) => i.review_status === 'completed')

  return (
    <div className={clsx('flex flex-col gap-2', className)}>
      {/* ヘッダー */}
      <div className="flex items-center gap-2">
        <ClipboardList size={14} className="text-amber-400" />
        <span className="text-xs font-semibold text-slate-300">要確認ラリー</span>
        {pending.length > 0 && (
          <span className="ml-auto text-[10px] bg-amber-500/20 text-amber-300 border border-amber-500/40 rounded px-1.5 py-0.5 font-medium">
            {pending.length} 件
          </span>
        )}
        {loading && <RefreshCw size={12} className="text-slate-500 animate-spin ml-1" />}
      </div>

      {/* 未完了 */}
      {pending.length === 0 && !loading ? (
        <div className="text-center text-slate-500 text-xs py-3">
          <CheckCircle size={14} className="inline mr-1 text-emerald-500" />
          要確認なし
        </div>
      ) : (
        <div className="flex flex-col gap-1 max-h-56 overflow-y-auto">
          {pending.map((item) => (
            <QueueItem
              key={item.rally_id}
              item={item}
              candidatesData={candidatesData}
              onMarkCompleted={onMarkCompleted}
              onJumpToRally={onJumpToRally}
            />
          ))}
        </div>
      )}

      {/* 完了済み（トグル表示） */}
      {completed.length > 0 && (
        <div>
          <button
            onClick={() => setShowCompleted((v) => !v)}
            className="text-[10px] text-slate-500 hover:text-slate-400 flex items-center gap-1"
          >
            {showCompleted ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
            完了済み {completed.length} 件
          </button>
          {showCompleted && (
            <div className="flex flex-col gap-1 mt-1 max-h-36 overflow-y-auto">
              {completed.map((item) => (
                <div
                  key={item.rally_id}
                  className="flex items-center gap-2 px-2 py-1 rounded bg-white/5 border border-white/10"
                >
                  <CheckCircle size={10} className="text-emerald-500 shrink-0" />
                  <span className="text-[10px] text-slate-400">R{item.rally_num}</span>
                  <span className="text-[9px] text-slate-600 truncate">
                    {item.cv_reason_codes.map((c) => REASON_LABELS[c] ?? c).join(' / ')}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
