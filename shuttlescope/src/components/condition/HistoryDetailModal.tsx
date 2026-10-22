import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import { apiDelete, newIdempotencyKey } from '@/api/client'
import { useAuth } from '@/hooks/useAuth'
import { MIcon } from '@/components/common/MIcon'

// 履歴詳細モーダル
// - 全ロール: 日付 / type / ccs / f1-f5 / hooper_index / session_rpe / 身体指標を表示
// - 質問票回答は選手本人の主観データなので、全ロールで読み取り専用 (編集 UI は持たない。
//   PATCH /api/conditions/{id} は questionnaire_json を受け付けず、回答の修正は選手本人の再入力のみ)
interface Props {
  record: Record<string, unknown>
  isLight: boolean
  onClose: () => void
}

// 表示対象の身体指標キー（値がある項目のみ表示）
const BODY_KEYS = [
  'weight_kg', 'muscle_mass_kg', 'body_fat_pct', 'body_fat_mass_kg',
  'lean_mass_kg', 'ecw_ratio',
  'arm_l_muscle_kg', 'arm_r_muscle_kg', 'leg_l_muscle_kg', 'leg_r_muscle_kg',
  'trunk_muscle_kg', 'bmr_kcal', 'sleep_hours',
] as const

function parseQuestionnaire(raw: unknown): Record<string, number> {
  if (!raw) return {}
  if (typeof raw === 'string') {
    try {
      const parsed = JSON.parse(raw)
      if (parsed && typeof parsed === 'object') return parsed as Record<string, number>
    } catch { /* noop */ }
    return {}
  }
  if (typeof raw === 'object') return raw as Record<string, number>
  return {}
}

export function HistoryDetailModal({ record, isLight, onClose }: Props) {
  const { t } = useTranslation()
  const { role } = useAuth()
  const qc = useQueryClient()
  // 削除は履歴一覧の各行ではなく、記録を開いたこの画面だけに置く (player には出さない)
  const canDelete = role != null && role !== 'player'

  const answers = useMemo(() => parseQuestionnaire(record['questionnaire_json']), [record])
  const [deleting, setDeleting] = useState(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  const overlayBg = 'bg-black/50'
  const panelCls = 'bg-[var(--ss-surface-1)] border-[var(--ss-border)] text-[var(--ss-t1)]'
  const muted = 'text-[var(--ss-t2)]'
  const sectionBorder = 'border-[var(--ss-border)]'

  const id = record['id'] as number | undefined
  const measuredAt = (record['measured_at'] as string | undefined) ?? ''
  const ctype = (record['condition_type'] as string | undefined) ?? ''
  const typeLabel = ctype === 'weekly'
    ? t('condition.history.type_weekly')
    : ctype === 'pre_match'
    ? t('condition.history.type_pre_match')
    : t('condition.history.type_body')

  const fmt = (v: unknown, digits = 1): string => {
    if (v == null || (typeof v !== 'number' && typeof v !== 'string')) return '—'
    const n = Number(v)
    if (!Number.isFinite(n)) return '—'
    return n.toFixed(digits)
  }

  const answerKeys = Object.keys(answers).sort()

  const handleDelete = async () => {
    if (!id) return
    if (!window.confirm(t('condition.history.delete_confirm') as string)) return
    setDeleting(true)
    setErrorMsg(null)
    try {
      await apiDelete(`/conditions/${id}`, { 'X-Idempotency-Key': newIdempotencyKey() })
      qc.invalidateQueries({ queryKey: ['conditions'] })
      onClose()
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setErrorMsg(`${t('condition.history_detail.delete_failed')}: ${msg}`)
    } finally {
      setDeleting(false)
    }
  }

  const metricRow = (label: string, value: unknown, digits = 1) => (
    <div className="flex justify-between text-sm">
      <span className={muted}>{label}</span>
      <span className="font-mono ss-num">{fmt(value, digits)}</span>
    </div>
  )

  const bodyItems = BODY_KEYS
    .map((k) => ({ key: k, value: record[k] }))
    .filter((x) => x.value != null)

  return (
    <div
      className={`fixed inset-0 z-50 flex items-center justify-center ${overlayBg} p-4`}
      onClick={onClose}
    >
      <div
        className={`relative w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-ss-lg border ${panelCls} shadow-[var(--e3)]`}
        onClick={(e) => e.stopPropagation()}
      >
        {/* ヘッダー */}
        <div className={`sticky top-0 z-10 flex items-center justify-between px-4 py-3 border-b ${sectionBorder} ${panelCls}`}>
          <div className="flex items-center gap-2">
            <h2 className="text-base font-semibold">{t('condition.history_detail.title')}</h2>
            <span className={`text-xs ss-num ${muted}`}>{measuredAt}</span>
            <span className="text-[10px] px-1.5 py-0.5 rounded-ss-sm border border-[var(--ss-border-strong)] text-[var(--ss-t2)]">
              {typeLabel}
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('condition.history_detail.close') as string}
            className="text-[var(--ss-t2)] hover:text-[var(--ss-t1)] duration-base ease-out"
          >
            <MIcon name="close" size={18} />
          </button>
        </div>

        <div className="p-4 space-y-4">
          {/* 指標 */}
          <section className={`rounded-ss-md border ${sectionBorder} p-3`}>
            <h3 className="text-xs font-semibold mb-2">{t('condition.history_detail.metrics_section')}</h3>
            <div className="grid grid-cols-2 gap-x-4 gap-y-1">
              {metricRow(t('condition.history.ccs'), record['ccs'], 2)}
              {metricRow(t('condition.history.hooper'), record['hooper_index'], 0)}
              {metricRow(t('condition.history.rpe'), record['session_rpe'], 0)}
              {metricRow('F1', record['f1'], 2)}
              {metricRow('F2', record['f2'], 2)}
              {metricRow('F3', record['f3'], 2)}
              {metricRow('F4', record['f4'], 2)}
              {metricRow('F5', record['f5'], 2)}
            </div>
          </section>

          {/* 身体指標 */}
          {bodyItems.length > 0 && (
            <section className={`rounded-ss-md border ${sectionBorder} p-3`}>
              <h3 className="text-xs font-semibold mb-2">{t('condition.history_detail.body_section')}</h3>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                {bodyItems.map((it) => (
                  <div key={it.key} className="flex justify-between text-sm">
                    <span className={muted}>{t(`condition.inbody.${it.key}`, it.key)}</span>
                    <span className="font-mono ss-num">{fmt(it.value)}</span>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* 質問票回答 */}
          <section className={`rounded-ss-md border ${sectionBorder} p-3`}>
            <h3 className="text-xs font-semibold mb-2">{t('condition.history_detail.questionnaire_section')}</h3>
            {answerKeys.length === 0 ? (
              <div className={`${muted} text-sm`}>{t('condition.history_detail.no_responses')}</div>
            ) : (
              <div className="space-y-1.5">
                {answerKeys.map((qid) => {
                  const val = answers[qid]
                  const qText = t(`condition.q.${qid}`, qid)
                  return (
                    <div key={qid} className="flex items-center justify-between gap-3">
                      <div className="flex-1 min-w-0">
                        <span className="text-xs font-mono mr-2">{qid}</span>
                        <span className="text-sm">{qText}</span>
                      </div>
                      <span className="font-mono ss-num text-sm w-8 text-right">{val}</span>
                    </div>
                  )
                })}
              </div>
            )}
          </section>

          {errorMsg && (
            <div className="text-sm text-[var(--ss-bad)] bg-[var(--ss-danger-tint)] border border-[var(--ss-danger-border)] rounded-ss-md px-3 py-2">
              {errorMsg}
            </div>
          )}
        </div>

        {/* フッター */}
        <div className={`sticky bottom-0 flex items-center gap-2 px-4 py-3 border-t ${sectionBorder} ${panelCls}`}>
          {canDelete && id != null && (
            <button
              type="button"
              onClick={handleDelete}
              disabled={deleting}
              className="mr-auto flex items-center gap-1 px-2 py-1 text-xs text-[var(--ss-bad)] hover:opacity-80 disabled:opacity-50"
            >
              <MIcon name="delete" size={14} />
              {t('condition.history.delete')}
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 rounded-ss-md text-sm border border-[var(--ss-border-strong)] text-[var(--ss-t1)] hover:bg-[var(--ss-surface-2)] duration-base ease-out"
          >
            {t('condition.history_detail.close')}
          </button>
        </div>
      </div>
    </div>
  )
}
