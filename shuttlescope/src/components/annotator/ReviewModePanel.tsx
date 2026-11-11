/**
 * U3 確認モード — その試合で保存済みのラリーとストロークを実データで一覧し、
 * 各ストロークをその場で編集する。
 *
 * F-T003-03 (muse T003 / E-90e8cfaa2891): 以前はここが実データ未接続で
 * 「この確認モードはまだ実データに接続されていません（開発中）」とだけ出て、
 * 保存したストロークを確認できなかった。いまは:
 *  - ラリー一覧: GET /rallies/match/{matchId}
 *  - ストローク一覧: GET /rallies/{rallyId}/strokes（id と編集に必要な全項目）
 *  - 編集: PUT /strokes/{strokeId}（ショット種別・着地ゾーン・打った人・意図タグ・
 *    メモ・打点の高さ）
 * 権限はいずれも既存の match scope（閲覧・編集判定）に従う。matchId が無い
 * （新規・未保存）ときは従来どおり案内を出す。
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { MIcon } from '@/components/common/MIcon'
import {
  getMatchRallies,
  getRallyStrokes,
  updateStroke,
  type ReviewRally,
  type ReviewStroke,
} from '@/api/review'

interface ReviewModePanelProps {
  /** 確認対象の試合 ID。未保存（新規）の場合は null/undefined。 */
  matchId?: number | null
}

const SHOT_TYPES = [
  'serve', 'clear', 'smash', 'drop', 'drive', 'net', 'lob', 'push', 'lift',
  'hairpin', 'block', 'drive_return', 'other',
]
const INTENT_TAGS = [
  'deep', 'net', 'body', 'sideline', 'cross', 'deception', 'clear_safe', 'other',
]
const CONTACT_HEIGHTS = ['overhead', 'side', 'underhand', 'scoop']

export function ReviewModePanel({ matchId }: ReviewModePanelProps) {
  const { t } = useTranslation()
  const [rallies, setRallies] = useState<ReviewRally[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [openRallyId, setOpenRallyId] = useState<number | null>(null)

  const loadRallies = useCallback(async () => {
    if (matchId == null) return
    setLoading(true)
    setError(null)
    try {
      setRallies(await getMatchRallies(matchId))
    } catch {
      setError(t('annotator.ux.review_load_error'))
    } finally {
      setLoading(false)
    }
  }, [matchId, t])

  useEffect(() => {
    void loadRallies()
  }, [loadRallies])

  return (
    <div className="flex flex-col h-full overflow-y-auto">
      <header className="flex items-center justify-between px-3 py-2 border-b border-[var(--ss-border)] shrink-0 bg-[var(--ss-surface-2)]">
        <div className="flex items-center gap-2 text-sm font-medium text-[var(--ss-t1)]">
          <MIcon name="visibility" size={18} />
          {t('annotator.ux.review_header')}
        </div>
        {matchId != null && (
          <span className="text-[10px] text-[var(--ss-t3)] ss-num">
            {t('annotator.ux.review_count_rally', { n: rallies.length })}
          </span>
        )}
      </header>
      <div className="flex-1 px-3 py-2 space-y-2">
        {matchId == null ? (
          <div className="text-xs text-[var(--ss-t3)] leading-relaxed">
            {t('annotator.ux.review_no_match')}
          </div>
        ) : loading ? (
          <div className="text-xs text-[var(--ss-t3)]">{t('annotator.ux.review_loading')}</div>
        ) : error ? (
          <div className="text-xs text-[var(--ss-danger)] leading-relaxed">
            {error}{' '}
            <button type="button" className="underline" onClick={() => void loadRallies()}>
              {t('annotator.ux.review_retry')}
            </button>
          </div>
        ) : rallies.length === 0 ? (
          <div className="text-xs text-[var(--ss-t3)] leading-relaxed">
            {t('annotator.ux.review_no_rallies')}
          </div>
        ) : (
          rallies.map((r) => (
            <RallyRow
              key={r.id}
              rally={r}
              open={openRallyId === r.id}
              onToggle={() => setOpenRallyId((cur) => (cur === r.id ? null : r.id))}
            />
          ))
        )}
      </div>
    </div>
  )
}

function RallyRow({
  rally,
  open,
  onToggle,
}: {
  rally: ReviewRally
  open: boolean
  onToggle: () => void
}) {
  const { t } = useTranslation()
  return (
    <div className="border border-[var(--ss-border)] rounded-ss-md overflow-hidden">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="w-full flex items-center justify-between px-2 py-1.5 text-xs bg-[var(--ss-surface-2)] hover:bg-[var(--ss-surface-3)]"
      >
        <span className="font-medium text-[var(--ss-t1)]">
          {t('annotator.ux.review_rally_label', { n: rally.rally_num })}
        </span>
        <span className="flex items-center gap-2 text-[10px] text-[var(--ss-t3)] ss-num">
          <span>{rally.score_a_after}-{rally.score_b_after}</span>
          <span>{rally.winner}</span>
          <MIcon name={open ? 'expand_less' : 'expand_more'} size={16} />
        </span>
      </button>
      {open && <RallyStrokes rallyId={rally.id} />}
    </div>
  )
}

function RallyStrokes({ rallyId }: { rallyId: number }) {
  const { t } = useTranslation()
  const [strokes, setStrokes] = useState<ReviewStroke[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setStrokes(await getRallyStrokes(rallyId))
    } catch {
      setError(t('annotator.ux.review_load_error'))
    } finally {
      setLoading(false)
    }
  }, [rallyId, t])

  useEffect(() => {
    void load()
  }, [load])

  const onSaved = useCallback((updated: ReviewStroke) => {
    setStrokes((cur) => cur.map((s) => (s.id === updated.id ? updated : s)))
  }, [])

  if (loading) {
    return <div className="px-2 py-1.5 text-[11px] text-[var(--ss-t3)]">{t('annotator.ux.review_loading')}</div>
  }
  if (error) {
    return (
      <div className="px-2 py-1.5 text-[11px] text-[var(--ss-danger)]">
        {error}{' '}
        <button type="button" className="underline" onClick={() => void load()}>
          {t('annotator.ux.review_retry')}
        </button>
      </div>
    )
  }
  if (strokes.length === 0) {
    return <div className="px-2 py-1.5 text-[11px] text-[var(--ss-t3)]">{t('annotator.ux.review_no_strokes')}</div>
  }
  return (
    <ul className="divide-y divide-[var(--ss-border)]">
      {strokes.map((s) => (
        <li key={s.id} className="px-2 py-1.5">
          <StrokeEditor stroke={s} onSaved={onSaved} />
        </li>
      ))}
    </ul>
  )
}

function StrokeEditor({
  stroke,
  onSaved,
}: {
  stroke: ReviewStroke
  onSaved: (s: ReviewStroke) => void
}) {
  const { t } = useTranslation()
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [shotType, setShotType] = useState(stroke.shot_type)
  const [landZone, setLandZone] = useState(stroke.land_zone ?? '')
  const [player, setPlayer] = useState(stroke.player)
  const [intentTag, setIntentTag] = useState(stroke.intent_tag ?? '')
  const [intentNote, setIntentNote] = useState(stroke.intent_note ?? '')
  const [contactHeight, setContactHeight] = useState(stroke.contact_height ?? '')

  const reset = useCallback(() => {
    setShotType(stroke.shot_type)
    setLandZone(stroke.land_zone ?? '')
    setPlayer(stroke.player)
    setIntentTag(stroke.intent_tag ?? '')
    setIntentNote(stroke.intent_note ?? '')
    setContactHeight(stroke.contact_height ?? '')
    setError(null)
  }, [stroke])

  const onSave = useCallback(async () => {
    setSaving(true)
    setError(null)
    try {
      const updated = await updateStroke(
        { id: stroke.id, stroke_num: stroke.stroke_num, player: stroke.player },
        {
          shot_type: shotType,
          land_zone: landZone || null,
          player,
          intent_tag: intentTag || null,
          intent_note: intentNote || null,
          contact_height: contactHeight || null,
        },
      )
      onSaved(updated)
      setEditing(false)
    } catch {
      setError(t('annotator.ux.review_save_error'))
    } finally {
      setSaving(false)
    }
  }, [stroke, shotType, landZone, player, intentTag, intentNote, contactHeight, onSaved, t])

  if (!editing) {
    return (
      <div className="flex items-start justify-between gap-2 text-[11px]">
        <div className="flex-1 min-w-0 space-y-0.5">
          <div className="flex items-center gap-2">
            <span className="ss-num text-[var(--ss-t3)]">#{stroke.stroke_num}</span>
            <span className="font-medium text-[var(--ss-t1)]">{stroke.shot_type}</span>
            <span className="text-[var(--ss-t2)]">{stroke.player}</span>
          </div>
          <div className="text-[10px] text-[var(--ss-t3)] space-x-2">
            <span>{t('annotator.ux.review_f_land')}: {stroke.land_zone ?? '—'}</span>
            <span>{t('annotator.ux.review_f_height')}: {stroke.contact_height ?? '—'}</span>
            <span>{t('annotator.ux.review_f_intent')}: {stroke.intent_tag ?? '—'}</span>
          </div>
          {stroke.intent_note && (
            <div className="text-[10px] text-[var(--ss-t3)] truncate">
              {t('annotator.ux.review_f_note')}: {stroke.intent_note}
            </div>
          )}
        </div>
        <button
          type="button"
          onClick={() => setEditing(true)}
          className="shrink-0 px-2 py-0.5 rounded-ss-sm text-[10px] bg-[var(--ss-surface-3)] text-[var(--ss-t2)] hover:text-[var(--ss-t1)]"
        >
          {t('annotator.ux.review_edit')}
        </button>
      </div>
    )
  }

  return (
    <div className="space-y-1.5 text-[11px]">
      <div className="flex items-center gap-2">
        <span className="ss-num text-[var(--ss-t3)]">#{stroke.stroke_num}</span>
      </div>
      <label className="block">
        <span className="text-[10px] text-[var(--ss-t3)]">{t('annotator.ux.review_f_shot')}</span>
        <select
          value={shotType}
          onChange={(e) => setShotType(e.target.value)}
          className="w-full bg-[var(--ss-surface-1)] border border-[var(--ss-border)] rounded-ss-sm px-1 py-0.5"
        >
          {SHOT_TYPES.includes(shotType) ? null : <option value={shotType}>{shotType}</option>}
          {SHOT_TYPES.map((v) => <option key={v} value={v}>{v}</option>)}
        </select>
      </label>
      <label className="block">
        <span className="text-[10px] text-[var(--ss-t3)]">{t('annotator.ux.review_f_player')}</span>
        <input
          value={player}
          onChange={(e) => setPlayer(e.target.value)}
          className="w-full bg-[var(--ss-surface-1)] border border-[var(--ss-border)] rounded-ss-sm px-1 py-0.5"
        />
      </label>
      <label className="block">
        <span className="text-[10px] text-[var(--ss-t3)]">{t('annotator.ux.review_f_land')}</span>
        <input
          value={landZone}
          onChange={(e) => setLandZone(e.target.value)}
          className="w-full bg-[var(--ss-surface-1)] border border-[var(--ss-border)] rounded-ss-sm px-1 py-0.5"
        />
      </label>
      <label className="block">
        <span className="text-[10px] text-[var(--ss-t3)]">{t('annotator.ux.review_f_height')}</span>
        <select
          value={contactHeight}
          onChange={(e) => setContactHeight(e.target.value)}
          className="w-full bg-[var(--ss-surface-1)] border border-[var(--ss-border)] rounded-ss-sm px-1 py-0.5"
        >
          <option value="">—</option>
          {CONTACT_HEIGHTS.map((v) => <option key={v} value={v}>{t(`enrichment.contact_height_${v}`)}</option>)}
        </select>
      </label>
      <label className="block">
        <span className="text-[10px] text-[var(--ss-t3)]">{t('annotator.ux.review_f_intent')}</span>
        <select
          value={intentTag}
          onChange={(e) => setIntentTag(e.target.value)}
          className="w-full bg-[var(--ss-surface-1)] border border-[var(--ss-border)] rounded-ss-sm px-1 py-0.5"
        >
          <option value="">—</option>
          {INTENT_TAGS.map((v) => <option key={v} value={v}>{v}</option>)}
        </select>
      </label>
      <label className="block">
        <span className="text-[10px] text-[var(--ss-t3)]">{t('annotator.ux.review_f_note')}</span>
        <input
          value={intentNote}
          maxLength={200}
          onChange={(e) => setIntentNote(e.target.value)}
          className="w-full bg-[var(--ss-surface-1)] border border-[var(--ss-border)] rounded-ss-sm px-1 py-0.5"
        />
      </label>
      {error && <div className="text-[10px] text-[var(--ss-danger)]">{error}</div>}
      <div className="flex items-center gap-2 pt-0.5">
        <button
          type="button"
          disabled={saving}
          onClick={() => void onSave()}
          className="px-2 py-0.5 rounded-ss-sm text-[10px] bg-[var(--ss-brand)] text-white disabled:opacity-50"
        >
          {saving ? t('annotator.ux.review_saving') : t('annotator.ux.review_save')}
        </button>
        <button
          type="button"
          disabled={saving}
          onClick={() => { reset(); setEditing(false) }}
          className="px-2 py-0.5 rounded-ss-sm text-[10px] bg-[var(--ss-surface-3)] text-[var(--ss-t2)]"
        >
          {t('annotator.ux.review_cancel')}
        </button>
      </div>
    </div>
  )
}
