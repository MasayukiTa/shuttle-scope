/**
 * ReviewQueuePanel — CV補助アノテーションのレビューキューパネル
 *
 * 表示内容:
 *   - 要確認ラリーの一覧
 *   - 理由コード（CV自動フラグ + 手動フラグ）
 *   - レビュー完了マーク
 *   - ラリーへのジャンプコールバック
 */
import { clsx } from 'clsx'
import { AlertTriangle, CheckCircle, ClipboardList, RefreshCw } from 'lucide-react'
import type { ReviewQueueItem } from '@/types/cv'

interface Props {
  items: ReviewQueueItem[]
  loading: boolean
  onMarkCompleted: (rallyId: number) => void
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

export function ReviewQueuePanel({
  items,
  loading,
  onMarkCompleted,
  onJumpToRally,
  className,
}: Props) {
  const pending = items.filter((i) => i.review_status !== 'completed')
  const completed = items.filter((i) => i.review_status === 'completed')

  return (
    <div className={clsx('flex flex-col gap-2', className)}>
      {/* ヘッダー */}
      <div className="flex items-center gap-2">
        <ClipboardList size={14} className="text-amber-400" />
        <span className="text-xs font-semibold text-slate-300">
          要確認ラリー
        </span>
        {pending.length > 0 && (
          <span className="ml-auto text-[10px] bg-amber-500/20 text-amber-300 border border-amber-500/40 rounded px-1.5 py-0.5 font-medium">
            {pending.length} 件
          </span>
        )}
        {loading && (
          <RefreshCw size={12} className="text-slate-500 animate-spin ml-1" />
        )}
      </div>

      {/* 未完了 */}
      {pending.length === 0 && !loading && (
        <div className="text-center text-slate-500 text-xs py-3">
          <CheckCircle size={14} className="inline mr-1 text-emerald-500" />
          要確認なし
        </div>
      )}

      <div className="flex flex-col gap-1 max-h-56 overflow-y-auto">
        {pending.map((item) => (
          <div
            key={item.rally_id}
            className="flex items-start gap-2 bg-amber-500/10 border border-amber-500/25 rounded px-2 py-1.5"
          >
            <AlertTriangle size={11} className="text-amber-400 mt-0.5 shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5">
                <span className="text-xs font-semibold text-white">
                  R{item.rally_num}
                </span>
                {item.cv_reason_codes.length > 0 && (
                  <span className="text-[9px] text-amber-300/70">
                    {item.cv_reason_codes
                      .map((c) => REASON_LABELS[c] ?? c)
                      .join(' / ')}
                  </span>
                )}
              </div>
            </div>
            <div className="flex items-center gap-1 shrink-0">
              {onJumpToRally && (
                <button
                  onClick={() => onJumpToRally(item.rally_id, item.rally_num)}
                  className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/20 hover:bg-blue-500/40 text-blue-300 transition-colors"
                >
                  移動
                </button>
              )}
              <button
                onClick={() => onMarkCompleted(item.rally_id)}
                className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/20 hover:bg-emerald-500/40 text-emerald-300 transition-colors"
                title="レビュー完了"
              >
                完了
              </button>
            </div>
          </div>
        ))}

        {/* 完了済み（折りたたみ） */}
        {completed.length > 0 && (
          <div className="text-[10px] text-slate-500 text-center pt-1">
            完了済み {completed.length} 件
          </div>
        )}
      </div>
    </div>
  )
}
