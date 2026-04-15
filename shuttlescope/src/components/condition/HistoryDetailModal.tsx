import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { apiPatch } from '@/api/client'
import { useAuth } from '@/hooks/useAuth'

// 履歴詳細モーダル
// - 全ロール: 日付 / type / ccs / f1-f5 / hooper_index / session_rpe / 身体指標を表示
// - analyst のみ: 質問票回答を 1-5 セレクタで編集し、PATCH /api/conditions/{id} で再スコアリング
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
  const isAnalyst = role === 'analyst'

  const initial = useMemo(() => parseQuestionnaire(record['questionnaire_json']), [record])
  const [answers, setAnswers] = useState<Record<string, number>>(initial)
  const [saving, setSaving] = useState(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [savedMsg, setSavedMsg] = useState<string | null>(null)

  const overlayBg = 'bg-black/50'
  const panelCls = isLight
    ? 'bg-white border-gray-200 text-gray-900'
    : 'bg-gray-800 border-gray-700 text-white'
  const muted = isLight ? 'text-gray-500' : 'text-gray-400'
  const sectionBorder = isLight ? 'border-gray-200' : 'border-gray-700'
  const selectCls = isLight
    ? 'border border-gray-300 bg-white text-gray-900 rounded px-2 py-1 text-sm'
    : 'border border-gray-600 bg-gray-900 text-white rounded px-2 py-1 text-sm'

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

  const handleChange = (qid: string, val: number) => {
    setAnswers((prev) => ({ ...prev, [qid]: val }))
  }

  const handleSave = async () => {
    if (!id) return
    setSaving(true)
    setErrorMsg(null)
    setSavedMsg(null)
    try {
      await apiPatch(`/conditions/${id}`, { questionnaire_json: answers })
      qc.invalidateQueries({ queryKey: ['conditions'] })
      setSavedMsg(t('condition.history_detail.saved'))
      onClose()
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setErrorMsg(`${t('condition.history_detail.save_failed')}: ${msg}`)
    } finally {
      setSaving(false)
    }
  }

  const metricRow = (label: string, value: unknown, digits = 1) => (
    <div className="flex justify-between text-sm">
      <span className={muted}>{label}</span>
      <span className="font-mono">{fmt(value, digits)}</span>
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
        className={`relative w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-lg border ${panelCls} shadow-xl`}
        onClick={(e) => e.stopPropagation()}
      >
        {/* ヘッダー */}
        <div className={`sticky top-0 z-10 flex items-center justify-between px-4 py-3 border-b ${sectionBorder} ${panelCls}`}>
          <div className="flex items-center gap-2">
            <h2 className="text-base font-semibold">{t('condition.history_detail.title')}</h2>
            <span className={`text-xs ${muted}`}>{measuredAt}</span>
            <span className={`text-[10px] px-1.5 py-0.5 rounded border ${isLight ? 'border-gray-300 text-gray-600' : 'border-gray-600 text-gray-300'}`}>
              {typeLabel}
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('condition.history_detail.close') as string}
            className={isLight ? 'text-gray-500 hover:text-gray-800' : 'text-gray-400 hover:text-white'}
          >
            <X size={18} />
          </button>
        </div>

        <div className="p-4 space-y-4">
          {/* 指標 */}
          <section className={`rounded border ${sectionBorder} p-3`}>
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
            <section className={`rounded border ${sectionBorder} p-3`}>
              <h3 className="text-xs font-semibold mb-2">{t('condition.history_detail.body_section')}</h3>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                {bodyItems.map((it) => (
                  <div key={it.key} className="flex justify-between text-sm">
                    <span className={muted}>{t(`condition.inbody.${it.key}`, it.key)}</span>
                    <span className="font-mono">{fmt(it.value)}</span>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* 質問票回答 */}
          <section className={`rounded border ${sectionBorder} p-3`}>
            <h3 className="text-xs font-semibold mb-2">{t('condition.history_detail.questionnaire_section')}</h3>
            {isAnalyst && answerKeys.length > 0 && (
              <div className={`text-[11px] ${muted} mb-2`}>
                {t('condition.history_detail.edit_hint')}
              </div>
            )}
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
                      {isAnalyst ? (
                        <select
                          className={selectCls}
                          value={val}
                          onChange={(e) => handleChange(qid, Number(e.target.value))}
                        >
                          {[1, 2, 3, 4, 5].map((n) => (
                            <option key={n} value={n}>{n}</option>
                          ))}
                        </select>
                      ) : (
                        <span className="font-mono text-sm w-8 text-right">{val}</span>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </section>

          {errorMsg && (
            <div className="text-sm text-red-500 bg-red-500/10 border border-red-500/30 rounded px-3 py-2">
              {errorMsg}
            </div>
          )}
          {savedMsg && (
            <div className="text-sm text-green-500 bg-green-500/10 border border-green-500/30 rounded px-3 py-2">
              {savedMsg}
            </div>
          )}
        </div>

        {/* フッター */}
        <div className={`sticky bottom-0 flex justify-end gap-2 px-4 py-3 border-t ${sectionBorder} ${panelCls}`}>
          <button
            type="button"
            onClick={onClose}
            className={`px-3 py-1.5 rounded text-sm ${isLight ? 'border border-gray-300 hover:bg-gray-100' : 'border border-gray-600 hover:bg-gray-700'}`}
          >
            {t('condition.history_detail.close')}
          </button>
          {isAnalyst && id != null && answerKeys.length > 0 && (
            <button
              type="button"
              onClick={handleSave}
              disabled={saving}
              className="px-4 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded text-sm font-medium"
            >
              {saving ? t('condition.history_detail.saving') : t('condition.history_detail.save')}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
