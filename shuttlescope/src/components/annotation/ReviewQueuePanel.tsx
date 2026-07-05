/**
 * ReviewQueuePanel — CV補助アノテーションのレビューキューパネル
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { clsx } from 'clsx'
import type { ReviewQueueItem, CVCandidatesData } from '@/types/cv'
import { MIcon } from '@/components/common/MIcon'

interface Props {
  items: ReviewQueueItem[]
  loading: boolean
  onMarkCompleted: (rallyId: number) => void
  candidatesData?: CVCandidatesData | null
  onJumpToRally?: (rallyId: number, rallyNum: number) => void
  className?: string
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
        'text-[9px] font-mono ss-num px-1 rounded-ss-sm',
        pct >= 70 ? 'bg-[var(--ss-surface-2)] text-[var(--ss-success)]' :
        pct >= 45 ? 'bg-[var(--ss-surface-2)] text-[var(--ss-brand)]' : 'bg-[var(--ss-surface-2)] text-[var(--ss-warn)]'
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
  const { t } = useTranslation()
  const [expanded, setExpanded] = useState(false)
  const reasonLabel = (c: string) => t(`review_queue.reason.${c}`, { defaultValue: c })
  const { data: dataReasons, quality: qualityReasons, other } = groupReasons(item.cv_reason_codes)
  const hasReasons = item.cv_reason_codes.length > 0
  const allReasonLabels = item.cv_reason_codes.map(reasonLabel)

  const rallyCandidate = candidatesData?.rallies?.[String(item.rally_id)]
  const summary = rallyCandidate?.cv_confidence_summary

  return (
    <div className="flex flex-col bg-[var(--ss-warn-tint)] border border-[var(--ss-warning-border)] rounded-ss-md px-2 py-1.5 gap-0.5">
      <div className="flex items-start gap-2">
        <MIcon name="warning" size={11} className="text-[var(--ss-warn)] mt-0.5 shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-xs font-semibold ss-num text-[var(--ss-t1)]">R{item.rally_num}</span>
            {summary && (
              <>
                <ConfidencePill value={summary.land_zone_fill_rate} label={t('review_queue.land_pill')} />
                <ConfidencePill value={summary.hitter_fill_rate} label={t('review_queue.hitter_pill')} />
              </>
            )}
          </div>
          {hasReasons && (
            <button
              onClick={() => setExpanded((v) => !v)}
              className="flex items-center gap-0.5 text-[9px] text-[var(--ss-warn)] hover:text-[var(--ss-warn)] mt-0.5 transition-colors duration-fast ease-out"
            >
              {expanded ? <MIcon name="expand_more" size={9} /> : <MIcon name="chevron_right" size={9} />}
              {allReasonLabels.join(' / ')}
            </button>
          )}
          {expanded && (
            <div className="mt-0.5 flex flex-col gap-0.5 pl-2">
              {dataReasons.length > 0 && (
                <div className="text-[9px] text-[var(--ss-warn)]">
                  <span className="text-[var(--ss-t3)] mr-1">{t('review_queue.data_label')}</span>
                  {dataReasons.map(reasonLabel).join(' · ')}
                </div>
              )}
              {qualityReasons.length > 0 && (
                <div className="text-[9px] text-[var(--ss-warn)]">
                  <span className="text-[var(--ss-t3)] mr-1">{t('review_queue.quality_label')}</span>
                  {qualityReasons.map(reasonLabel).join(' · ')}
                </div>
              )}
              {other.length > 0 && (
                <div className="text-[9px] text-[var(--ss-t3)]">
                  {other.map(reasonLabel).join(' · ')}
                </div>
              )}
            </div>
          )}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {onJumpToRally && (
            <button
              onClick={() => onJumpToRally(item.rally_id, item.rally_num)}
              className="text-[10px] px-1.5 py-0.5 rounded-ss-sm bg-[var(--ss-brand-tint)] hover:bg-[var(--ss-brand-tint)] text-[var(--ss-brand)] transition-colors duration-fast ease-out"
              title={t('review_queue.jump_title')}
            >
              {t('review_queue.jump_btn')}
            </button>
          )}
          <button
            onClick={() => onMarkCompleted(item.rally_id)}
            className="text-[10px] px-1.5 py-0.5 rounded-ss-sm bg-[var(--ss-success-tint)] hover:bg-[var(--ss-success-tint)] text-[var(--ss-success)] transition-colors duration-fast ease-out"
            title={t('review_queue.mark_complete_title')}
          >
            {t('review_queue.mark_complete_btn')}
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
  const { t } = useTranslation()
  const [showCompleted, setShowCompleted] = useState(false)
  const pending = items.filter((i) => i.review_status !== 'completed')
  const completed = items.filter((i) => i.review_status === 'completed')
  const reasonLabel = (c: string) => t(`review_queue.reason.${c}`, { defaultValue: c })

  return (
    <div className={clsx('flex flex-col gap-2', className)}>
      <div className="flex items-center gap-2">
        <MIcon name="assignment" size={14} className="text-[var(--ss-warn)]" />
        <span className="text-xs font-semibold text-[var(--ss-t2)]">{t('review_queue.title')}</span>
        {pending.length > 0 && (
          <span className="ml-auto text-[10px] ss-num bg-[var(--ss-warn-tint)] text-[var(--ss-warn)] border border-[var(--ss-warning-border)] rounded-ss-sm px-1.5 py-0.5 font-medium">
            {t('review_queue.count_items', { count: pending.length })}
          </span>
        )}
        {loading && <MIcon name="refresh" size={12} className="text-[var(--ss-t3)] animate-spin ml-1" />}
      </div>

      {pending.length === 0 && !loading ? (
        <div className="text-center text-[var(--ss-t3)] text-xs py-3">
          <MIcon name="check_circle" size={14} className="inline mr-1 text-[var(--ss-success)]" />
          {t('review_queue.none')}
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

      {completed.length > 0 && (
        <div>
          <button
            onClick={() => setShowCompleted((v) => !v)}
            className="text-[10px] text-[var(--ss-t3)] hover:text-[var(--ss-t2)] flex items-center gap-1 transition-colors duration-fast ease-out"
          >
            {showCompleted ? <MIcon name="expand_more" size={10} /> : <MIcon name="chevron_right" size={10} />}
            {t('review_queue.completed_section', { count: completed.length })}
          </button>
          {showCompleted && (
            <div className="flex flex-col gap-1 mt-1 max-h-36 overflow-y-auto">
              {completed.map((item) => (
                <div
                  key={item.rally_id}
                  className="flex items-center gap-2 px-2 py-1 rounded-ss-sm bg-[var(--ss-surface-2)] border border-[var(--ss-border)]"
                >
                  <MIcon name="check_circle" size={10} className="text-[var(--ss-success)] shrink-0" />
                  <span className="text-[10px] ss-num text-[var(--ss-t3)]">R{item.rally_num}</span>
                  <span className="text-[9px] text-[var(--ss-t3)] truncate">
                    {item.cv_reason_codes.map(reasonLabel).join(' / ')}
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
