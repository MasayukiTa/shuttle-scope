import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useConditionMaster } from '@/hooks/useConditionMaster'
import { useSubmitQuestionnaire, ConditionResult } from '@/hooks/useConditions'
import { QuestionnaireRunner } from '@/components/condition/QuestionnaireRunner'

interface Props {
  playerId: number
  measuredAt: string
  matchId?: number | null
  isLight?: boolean
  onSubmitted?: (result: ConditionResult) => void
}

// Phase 2: 試合直前 10 問。所要 1 分目安。
export function PreMatchQuestionnaire({ playerId, measuredAt, matchId, isLight, onSubmitted }: Props) {
  const { t } = useTranslation()
  const { data: master, isLoading } = useConditionMaster('pre_match')
  const [responses, setResponses] = useState<Record<string, number>>({})
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  const mut = useSubmitQuestionnaire()

  const items = master?.items ?? []
  const totalQuestions = items.length
  const answered = useMemo(
    () => items.filter((q) => responses[String(q.id)] != null).length,
    [items, responses],
  )
  const complete = answered >= totalQuestions && totalQuestions > 0

  const labelMuted = isLight ? 'text-xs text-gray-600' : 'text-xs text-gray-400'
  const pct = totalQuestions ? Math.round((answered / totalQuestions) * 100) : 0

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
        condition_type: 'pre_match',
        responses,
        match_id: matchId ?? null,
      })
      if (onSubmitted && result) onSubmitted(result)
      setResponses({})
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setErrorMsg(`${t('condition.save_failed')}: ${msg}`)
    }
  }

  if (isLoading) {
    return <div className={labelMuted}>{t('app.loading')}</div>
  }

  return (
    <div className="space-y-4 max-w-3xl">
      <div>
        <h2 className="text-base font-semibold">{t('condition.prematch.title')}</h2>
        <p className={labelMuted}>{t('condition.prematch.intro')}</p>
      </div>

      <div className={`sticky top-0 z-10 ${isLight ? 'bg-gray-50' : 'bg-gray-900'} py-2`}>
        <div className="flex items-center gap-3">
          <div className="flex-1 h-2 bg-gray-700/30 rounded overflow-hidden">
            <div className="h-full bg-blue-500 transition-all" style={{ width: `${pct}%` }} />
          </div>
          <div className="text-xs whitespace-nowrap">
            {t('condition.prematch.progress', { n: answered, total: totalQuestions })}
          </div>
        </div>
      </div>

      <QuestionnaireRunner
        items={items}
        responses={responses}
        onChange={setResponses}
        isLight={isLight}
      />

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
          {mut.isPending ? '...' : t('condition.prematch.submit')}
        </button>
      </div>
    </div>
  )
}
