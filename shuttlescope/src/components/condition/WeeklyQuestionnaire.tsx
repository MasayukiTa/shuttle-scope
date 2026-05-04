import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useConditionMaster } from '@/hooks/useConditionMaster'
import { useSubmitQuestionnaire, ConditionResult } from '@/hooks/useConditions'
import { QuestionnaireRunner } from '@/components/condition/QuestionnaireRunner'

interface Props {
  playerId: number
  measuredAt: string
  isLight?: boolean
  onSubmitted?: (result: ConditionResult) => void
}

// Phase 2: 週次質問票（44 本質 + 4 妥当性 = 48 問 + 補助）
export function WeeklyQuestionnaire({ playerId, measuredAt, isLight, onSubmitted }: Props) {
  const { t } = useTranslation()
  const { data: master, isLoading } = useConditionMaster('weekly')
  const [responses, setResponses] = useState<Record<string, number>>({})
  const [sleepHours, setSleepHours] = useState<string>('')
  const [injuryNotes, setInjuryNotes] = useState<string>('')
  const [generalComment, setGeneralComment] = useState<string>('')
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  const mut = useSubmitQuestionnaire()

  const items = master?.items ?? []
  const totalQuestions = items.length
  const answered = useMemo(
    () => items.filter((q) => responses[String(q.id)] != null).length,
    [items, responses],
  )
  const complete = answered >= totalQuestions && totalQuestions > 0

  const inputCls = isLight
    ? 'w-full border border-gray-300 bg-white text-gray-900 rounded px-2 py-1.5 text-sm'
    : 'w-full border border-gray-600 bg-gray-800 text-white rounded px-2 py-1.5 text-sm'
  const labelMuted = isLight ? 'text-xs text-gray-600' : 'text-xs text-gray-400'

  const handleSubmit = async () => {
    setErrorMsg(null)
    if (!complete) {
      setErrorMsg(t('condition.weekly.incomplete'))
      return
    }
    try {
      const result = await mut.mutateAsync({
        player_id: playerId,
        measured_at: measuredAt,
        condition_type: 'weekly',
        responses,
        auxiliary: {
          sleep_hours: sleepHours === '' ? null : Number(sleepHours),
          injury_notes: injuryNotes || null,
          general_comment: generalComment || null,
        },
      })
      if (onSubmitted && result) onSubmitted(result)
      setResponses({})
      setSleepHours('')
      setInjuryNotes('')
      setGeneralComment('')
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setErrorMsg(`${t('condition.save_failed')}: ${msg}`)
    }
  }

  if (isLoading) {
    return <div className={labelMuted}>{t('app.loading')}</div>
  }

  const pct = totalQuestions ? Math.round((answered / totalQuestions) * 100) : 0

  return (
    <div className="space-y-4 max-w-3xl">
      <div>
        <h2 className="text-base font-semibold">{t('condition.weekly.title')}</h2>
        <p className={labelMuted}>{t('condition.weekly.intro')}</p>
      </div>

      <div className={`sticky top-0 z-10 ${isLight ? 'bg-gray-50' : 'bg-gray-900'} py-2`}>
        <div className="flex items-center gap-3">
          <div className="flex-1 h-2 bg-gray-700/30 rounded overflow-hidden">
            <div className="h-full bg-blue-500 transition-all" style={{ width: `${pct}%` }} />
          </div>
          <div className="text-xs whitespace-nowrap">
            {t('condition.weekly.progress', { n: answered, total: totalQuestions })}
          </div>
        </div>
      </div>

      <QuestionnaireRunner
        items={items}
        responses={responses}
        onChange={setResponses}
        isLight={isLight}
      />

      {/* 補助（任意） */}
      <section className={`rounded-lg border p-4 ${isLight ? 'bg-white border-gray-200' : 'bg-gray-800 border-gray-700'}`}>
        <h3 className="text-sm font-semibold mb-3">{t('condition.section_auxiliary')}</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <label className="flex flex-col gap-1">
            <span className={labelMuted}>{t('condition.aux.sleep_hours')}</span>
            <input
              type="number"
              step="0.1"
              min={0}
              max={24}
              inputMode="decimal"
              className={inputCls}
              value={sleepHours}
              onChange={(e) => setSleepHours(e.target.value)}
            />
          </label>
        </div>
        <label className="flex flex-col gap-1 mt-3">
          <span className={labelMuted}>{t('condition.aux.injury_notes')}</span>
          <textarea
            rows={2}
            className={inputCls}
            value={injuryNotes}
            onChange={(e) => setInjuryNotes(e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1 mt-3">
          <span className={labelMuted}>{t('condition.aux.general_comment')}</span>
          <textarea
            rows={3}
            className={inputCls}
            value={generalComment}
            onChange={(e) => setGeneralComment(e.target.value)}
          />
        </label>
      </section>

      {errorMsg && (
        <div className="text-sm text-red-500 bg-red-500/10 border border-red-500/30 rounded px-3 py-2">
          {errorMsg}
        </div>
      )}

      <div className="flex justify-end">
        <button
          onClick={handleSubmit}
          disabled={mut.isPending || !complete}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded text-sm font-medium"
        >
          {mut.isPending ? '...' : t('condition.weekly.submit')}
        </button>
      </div>
    </div>
  )
}
