/**
 * CVScanPanel — ラリー無し動画の全体走査の確認パネル（operator 専用）
 *
 * admin / analyst / coach にだけ描画する（RoleGuard。player / demo / llm には何も出さず、
 * API も呼ばない）。CV はラリーを作らない。人が区間に対して reject / accept / assign を
 * 記録し、既存ラリーの動画時刻へ「採用」できるだけ。自動採用はしない。
 *
 * 区間のデータ不足（data_insufficient）と片側欠け（open_ended）は数字を出さず、状態として示す。
 * signal_score は「発火した信号数 / 3」の平均で、統計的な確からしさではない。
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { clsx } from 'clsx'
import { RoleGuard } from '@/components/common/RoleGuard'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { MIcon } from '@/components/common/MIcon'
import {
  useCVScan,
  segmentKey,
  type CVSegment,
  type SegmentDecision,
} from '@/hooks/annotator/useCVScan'

interface Props {
  matchId: number
  /** 動画を指定秒へ移動する（アノテータの video 要素）。渡されなければ区間クリックでは動かさない */
  onSeek?: (sec: number) => void
  className?: string
}

const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)

/** mm:ss（1 時間以上は h:mm:ss）。数値でなければ null（0 や NaN にしない）。 */
export function formatClock(sec: number | null | undefined): string | null {
  if (!isNum(sec) || sec < 0) return null
  const total = Math.floor(sec)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`
}

function PhaseBar({ value }: { value: number | null | undefined }) {
  const pct = isNum(value) ? Math.max(0, Math.min(100, Math.round(value * 100))) : null
  return (
    <div className="h-1.5 rounded-ss-sm bg-[var(--ss-surface-3)] overflow-hidden">
      {pct != null && (
        <div className="h-full bg-[var(--ss-brand)] transition-all duration-fast ease-out" style={{ width: `${pct}%` }} />
      )}
    </div>
  )
}

function SegmentRow({
  seg,
  ctrl,
  onSeek,
}: {
  seg: CVSegment
  ctrl: ReturnType<typeof useCVScan>
  onSeek?: (sec: number) => void
}) {
  const { t } = useTranslation()
  const key = segmentKey(seg.start_sec, seg.end_sec)
  const [rallyId, setRallyId] = useState<string>('')
  const [adoptArmed, setAdoptArmed] = useState(false)

  const busy = ctrl.busyKey === key
  const failure = ctrl.rowFailures[key]
  const notice = ctrl.rowNotices[key]
  const insufficient = seg.data_status === 'data_insufficient'
  const closed = isNum(seg.start_sec) && isNum(seg.end_sec)
  const seekTo = isNum(seg.start_sec) ? seg.start_sec : isNum(seg.end_sec) ? seg.end_sec : null
  const picked = rallyId !== '' ? Number(rallyId) : null
  const noRallies = ctrl.rallies.length === 0

  const startTxt = formatClock(seg.start_sec) ?? t('cv_scan.seg.unknown_time')
  const endTxt = formatClock(seg.end_sec) ?? t('cv_scan.seg.unknown_time')
  const durTxt = formatClock(seg.duration) ?? t('cv_scan.seg.unknown_value')
  const covTxt = isNum(seg.coverage_ratio) ? `${Math.round(seg.coverage_ratio * 100)}%` : t('cv_scan.seg.unknown_value')

  // signals N/3 は confidence_basis が signals_fired/3 のときだけ数字にする
  let signalsTxt = t('cv_scan.seg.signals_none')
  if (isNum(seg.signal_score)) {
    if (seg.confidence_basis === 'signals_fired/3') {
      const n = Math.round(seg.signal_score * 3 * 10) / 10
      signalsTxt = t('cv_scan.seg.signals', { n })
    } else {
      signalsTxt = t('cv_scan.seg.signals_other_basis', { basis: seg.confidence_basis ?? '?' })
    }
  }

  let badgeTxt: string
  let badgeClass: string
  let uncertaintyTxt: string
  if (seg.open_ended) {
    badgeTxt = t(seg.open_side === 'start_missing' ? 'cv_scan.seg.badge_open_start_missing' : 'cv_scan.seg.badge_open_end_missing')
    badgeClass = 'border-[var(--ss-warning-border)] bg-[var(--ss-warning-bg)] text-[var(--ss-warning-text)]'
    uncertaintyTxt = t('cv_scan.seg.uncertainty_open')
  } else if (insufficient) {
    badgeTxt = t('cv_scan.seg.badge_insufficient')
    badgeClass = 'border-[var(--ss-danger-border)] bg-[var(--ss-danger-bg)] text-[var(--ss-danger-text)]'
    uncertaintyTxt = t('cv_scan.seg.uncertainty_insufficient')
  } else {
    badgeTxt = t('cv_scan.seg.badge_unverified')
    badgeClass = 'border-[var(--ss-border)] bg-[var(--ss-surface-2)] text-[var(--ss-t2)]'
    uncertaintyTxt = t('cv_scan.seg.uncertainty_ok')
  }

  const decisionText = (d: SegmentDecision): string => {
    const when = d.decided_at ? ` (${d.decided_at.slice(0, 16).replace('T', ' ')})` : ''
    if (d.action === 'assign') {
      const base = t(d.adopted ? 'cv_scan.decision.assign_adopted' : 'cv_scan.decision.assign', { id: d.rally_id ?? '?' })
      return base + when
    }
    return t(d.action === 'reject' ? 'cv_scan.decision.reject' : 'cv_scan.decision.accept') + when
  }

  const runAdopt = async () => {
    if (picked == null) return
    if (!adoptArmed) {
      setAdoptArmed(true)
      return
    }
    setAdoptArmed(false)
    await ctrl.adopt(seg, picked)
  }

  return (
    <li
      data-testid="cv-scan-segment"
      className="rounded-ss-sm border border-[var(--ss-border)] bg-[var(--ss-surface-1)] px-2 py-1.5 text-xs flex flex-col gap-1"
    >
      <div className="flex items-center gap-1.5 flex-wrap">
        <button
          type="button"
          onClick={() => seekTo != null && onSeek?.(seekTo)}
          disabled={seekTo == null || !onSeek}
          title={t('cv_scan.seg.seek')}
          className="inline-flex items-center gap-1 font-mono ss-num text-[var(--ss-t1)] hover:text-[var(--ss-brand)] disabled:opacity-60 disabled:hover:text-[var(--ss-t1)]"
        >
          <MIcon name="play_arrow" size={12} />
          <span>{startTxt} - {endTxt}</span>
        </button>
        <span className="text-[var(--ss-t3)]">{t('cv_scan.seg.duration', { value: durTxt })}</span>
        <span className={clsx('px-1.5 py-0.5 rounded-ss-pill border text-[10px]', badgeClass)}>{badgeTxt}</span>
      </div>

      <div className="flex items-center gap-x-3 gap-y-0.5 flex-wrap text-[10px] text-[var(--ss-t2)]">
        <span className="ss-num">{signalsTxt}</span>
        <span className="ss-num">{t('cv_scan.seg.coverage', { value: covTxt })}</span>
        {isNum(seg.sample_count) ? (
          <ConfidenceBadge sampleSize={seg.sample_count} compact />
        ) : (
          <span className="ss-num">{t('cv_scan.seg.sample_count', { value: t('cv_scan.seg.unknown_value') })}</span>
        )}
      </div>
      <div className="text-[10px] text-[var(--ss-t3)]">{uncertaintyTxt}</div>

      {seg.latest_decision && (
        <div className="text-[10px] text-[var(--ss-t2)] flex items-center gap-1" data-testid="cv-scan-latest-decision">
          <MIcon name="how_to_reg" size={11} />
          <span>{t('cv_scan.decision.latest', { text: decisionText(seg.latest_decision) })}</span>
        </div>
      )}

      <div className="flex items-center gap-1 flex-wrap">
        <button
          type="button"
          disabled={busy}
          onClick={() => void ctrl.decide(seg, 'reject')}
          className="px-1.5 py-0.5 rounded-ss-sm border border-[var(--ss-border)] text-[var(--ss-t1)] hover:bg-[var(--ss-surface-2)] disabled:opacity-50"
        >
          {t('cv_scan.action.reject')}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => void ctrl.decide(seg, 'accept')}
          className="px-1.5 py-0.5 rounded-ss-sm border border-[var(--ss-border)] text-[var(--ss-t1)] hover:bg-[var(--ss-surface-2)] disabled:opacity-50"
        >
          {t('cv_scan.action.accept')}
        </button>
        <select
          value={rallyId}
          onChange={(e) => {
            setRallyId(e.target.value)
            setAdoptArmed(false)
          }}
          disabled={busy || noRallies}
          aria-label={t('cv_scan.action.pick_rally')}
          className="px-1 py-0.5 rounded-ss-sm border border-[var(--ss-border)] bg-[var(--ss-surface-1)] text-[var(--ss-t1)] max-w-[9rem]"
        >
          <option value="">{t('cv_scan.action.pick_rally')}</option>
          {ctrl.rallies.map((r) => (
            <option key={r.id} value={r.id}>
              {t('cv_scan.action.rally_option', { num: r.rally_num, id: r.id })}
            </option>
          ))}
        </select>
        <button
          type="button"
          disabled={busy || picked == null}
          onClick={() => picked != null && void ctrl.decide(seg, 'assign', picked)}
          className="px-1.5 py-0.5 rounded-ss-sm border border-[var(--ss-border)] text-[var(--ss-t1)] hover:bg-[var(--ss-surface-2)] disabled:opacity-50"
        >
          {t('cv_scan.action.assign')}
        </button>
        <button
          type="button"
          disabled={busy || picked == null || !closed || insufficient}
          onClick={() => void runAdopt()}
          title={!closed || insufficient ? t('cv_scan.action.adopt_unavailable') : t('cv_scan.action.adopt_hint')}
          className={clsx(
            'px-1.5 py-0.5 rounded-ss-sm border disabled:opacity-50',
            adoptArmed
              ? 'border-[var(--ss-warning-border)] bg-[var(--ss-warning-bg)] text-[var(--ss-warning-text)]'
              : 'border-[var(--ss-brand-border)] bg-[var(--ss-brand-tint)] text-[var(--ss-brand)]',
          )}
        >
          {adoptArmed ? t('cv_scan.action.adopt_confirm') : t('cv_scan.action.adopt')}
        </button>
      </div>
      {noRallies && !ctrl.ralliesLoading && (
        <div className="text-[10px] text-[var(--ss-t3)]">
          {ctrl.ralliesFailure ? t('cv_scan.action.rallies_failed', { message: ctrl.ralliesFailure.detail }) : t('cv_scan.action.rallies_empty')}
        </div>
      )}

      {failure && (
        <div role="alert" className="text-[10px] text-[var(--ss-danger-text)] flex items-start gap-1" data-testid="cv-scan-row-error">
          <MIcon name="error" size={11} className="shrink-0 mt-px" />
          <span>
            {failure.status === 409
              ? t('cv_scan.action.adopt_refused', { message: failure.detail })
              : t('cv_scan.action.row_failed', { message: failure.detail })}
          </span>
        </div>
      )}
      {notice && (
        <div role="status" className="text-[10px] text-[var(--ss-success-text)] flex items-center gap-1">
          <MIcon name="check_circle" size={11} />
          <span>{t('cv_scan.action.adopt_done', { id: notice })}</span>
        </div>
      )}
    </li>
  )
}

function CVScanPanelBody({ matchId, onSeek, className }: Props) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [scanArmed, setScanArmed] = useState(false)
  const ctrl = useCVScan(matchId, open)
  const st = ctrl.scanStatus
  const phase = st?.phase ?? null
  const segs = ctrl.segmentsData

  const phaseLabel = phase ? t(`cv_scan.phase.${phase}`, { defaultValue: String(phase) }) : null
  const subErrors = [st?.tracknet?.error, st?.yolo?.error].filter((e): e is string => !!e)

  const startScan = async () => {
    if (!scanArmed) {
      setScanArmed(true)
      return
    }
    setScanArmed(false)
    await ctrl.startScan()
  }

  return (
    <div className={clsx('rounded-ss-md border p-2 shrink-0 bg-[var(--ss-surface-1)] border-[var(--ss-border)]', className)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="w-full flex items-center justify-between text-[10px] font-semibold text-[var(--ss-t1)]"
      >
        <span className="inline-flex items-center gap-1">
          <MIcon name="travel_explore" size={12} />
          {t('cv_scan.title')}
        </span>
        <MIcon name={open ? 'expand_more' : 'chevron_right'} size={14} />
      </button>

      {open && (
        <div className="mt-2 flex flex-col gap-2 text-xs">
          <p className="text-[10px] text-[var(--ss-t3)]">{t('cv_scan.note_no_rally_creation')}</p>

          {/* ─ 走査 ─ */}
          <div className="rounded-ss-sm border border-[var(--ss-border)] p-2 flex flex-col gap-1.5">
            <div className="text-[10px] text-[var(--ss-warning-text)] flex items-start gap-1">
              <MIcon name="warning" size={11} className="shrink-0 mt-px" />
              <span>{t('cv_scan.cost_warning')}</span>
            </div>
            <div className="text-[10px] text-[var(--ss-t3)]">{t('cv_scan.exclusive_note')}</div>
            <div className="flex items-center gap-2 flex-wrap">
              <button
                type="button"
                onClick={() => void startScan()}
                disabled={ctrl.scanStarting || ctrl.scanActive}
                className={clsx(
                  'px-2 py-1 rounded-ss-sm border disabled:opacity-50',
                  scanArmed
                    ? 'border-[var(--ss-warning-border)] bg-[var(--ss-warning-bg)] text-[var(--ss-warning-text)]'
                    : 'border-[var(--ss-brand-border)] bg-[var(--ss-brand-tint)] text-[var(--ss-brand)]',
                )}
              >
                {ctrl.scanStarting ? t('cv_scan.starting') : scanArmed ? t('cv_scan.start_confirm') : t('cv_scan.start')}
              </button>
              {scanArmed && !ctrl.scanStarting && (
                <button
                  type="button"
                  onClick={() => setScanArmed(false)}
                  className="px-2 py-1 rounded-ss-sm border border-[var(--ss-border)] text-[var(--ss-t2)]"
                >
                  {t('cv_scan.cancel')}
                </button>
              )}
            </div>

            {ctrl.scanFailure && (
              <div role="alert" className="text-[10px] text-[var(--ss-danger-text)] flex items-start gap-1" data-testid="cv-scan-start-error">
                <MIcon name="error" size={11} className="shrink-0 mt-px" />
                <span>
                  {ctrl.scanFailure.status === 409
                    ? t('cv_scan.scan_busy', { message: ctrl.scanFailure.detail })
                    : t('cv_scan.scan_failed', { message: ctrl.scanFailure.detail })}
                </span>
              </div>
            )}

            {st && (
              <div className="flex flex-col gap-1" data-testid="cv-scan-progress">
                <div className="flex items-center justify-between text-[10px] text-[var(--ss-t2)]">
                  <span>{t('cv_scan.phase_label', { phase: phaseLabel })}</span>
                  {isNum(st.progress) && <span className="ss-num">{Math.round(st.progress * 100)}%</span>}
                </div>
                <PhaseBar value={st.progress} />
                <div className="flex gap-3 text-[10px] text-[var(--ss-t3)]">
                  <span className="ss-num">
                    {t('cv_scan.tracknet_label')}: {isNum(st.tracknet?.progress) ? `${Math.round(st.tracknet!.progress! * 100)}%` : t('cv_scan.seg.unknown_value')}
                  </span>
                  <span className="ss-num">
                    {t('cv_scan.yolo_label')}: {isNum(st.yolo?.progress) ? `${Math.round(st.yolo!.progress! * 100)}%` : t('cv_scan.seg.unknown_value')}
                  </span>
                </div>
                {phase === 'error' && (
                  <div role="alert" className="text-[10px] text-[var(--ss-danger-text)]">
                    {t('cv_scan.scan_failed', { message: st.error ?? subErrors[0] ?? t('cv_scan.seg.unknown_value') })}
                  </div>
                )}
                {phase !== 'error' && subErrors.length > 0 && (
                  <div className="text-[10px] text-[var(--ss-warning-text)]">{subErrors.join(' / ')}</div>
                )}
              </div>
            )}

            {phase === 'done' && (
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-[10px] text-[var(--ss-success-text)]">{t('cv_scan.scan_done')}</span>
                <button
                  type="button"
                  onClick={() => void ctrl.buildSegments()}
                  disabled={ctrl.building}
                  className="px-2 py-1 rounded-ss-sm border border-[var(--ss-brand-border)] bg-[var(--ss-brand-tint)] text-[var(--ss-brand)] disabled:opacity-50"
                >
                  {ctrl.building ? t('cv_scan.building') : t('cv_scan.build')}
                </button>
              </div>
            )}
            {ctrl.buildFailure && (
              <div role="alert" className="text-[10px] text-[var(--ss-danger-text)]">
                {t('cv_scan.build_failed', { message: ctrl.buildFailure.detail })}
              </div>
            )}
          </div>

          {/* ─ 区間 ─ */}
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-semibold text-[var(--ss-t2)]">{t('cv_scan.segments_title')}</span>
              <button
                type="button"
                onClick={() => void ctrl.reloadSegments()}
                disabled={ctrl.segmentsLoading}
                aria-label={t('cv_scan.reload')}
                title={t('cv_scan.reload')}
                className="text-[var(--ss-t2)] hover:text-[var(--ss-t1)] disabled:opacity-50"
              >
                <MIcon name="refresh" size={12} />
              </button>
            </div>

            {ctrl.segmentsLoading && !segs && (
              <div className="text-[10px] text-[var(--ss-t3)]" data-testid="cv-scan-loading">{t('cv_scan.loading')}</div>
            )}
            {ctrl.segmentsFailure && (
              <div role="alert" className="text-[10px] text-[var(--ss-danger-text)]" data-testid="cv-scan-load-error">
                {t('cv_scan.load_failed', { message: ctrl.segmentsFailure.detail })}
              </div>
            )}
            {segs && segs.status === 'insufficient_data' && (
              <div className="text-[10px] text-[var(--ss-t2)] bg-[var(--ss-surface-2)] rounded-ss-sm px-2 py-1" data-testid="cv-scan-insufficient">
                <div className="font-semibold">{t('cv_scan.status_insufficient')}</div>
                {segs.reason && <div className="text-[var(--ss-t3)]">{segs.reason}</div>}
              </div>
            )}
            {segs && segs.status === 'no_segments' && (
              <div className="text-[10px] text-[var(--ss-t2)] bg-[var(--ss-surface-2)] rounded-ss-sm px-2 py-1" data-testid="cv-scan-none">
                {t('cv_scan.status_no_segments')}
              </div>
            )}
            {segs && segs.segments.length > 0 && (
              <>
                <div className="text-[10px] text-[var(--ss-t3)] ss-num">{t('cv_scan.segments_count', { count: segs.segments.length })}</div>
                <ul className="flex flex-col gap-1 max-h-72 overflow-y-auto pr-0.5">
                  {segs.segments.map((seg, i) => (
                    <SegmentRow
                      key={`${segmentKey(seg.start_sec, seg.end_sec)}#${i}`}
                      seg={seg}
                      ctrl={ctrl}
                      onSeek={onSeek}
                    />
                  ))}
                </ul>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

/** operator（admin / analyst / coach）だけに描画する。それ以外は何も描かず API も呼ばない。 */
export function CVScanPanel(props: Props) {
  return (
    <RoleGuard allowedRoles={['analyst', 'coach']} fallback={null}>
      <CVScanPanelBody {...props} />
    </RoleGuard>
  )
}
