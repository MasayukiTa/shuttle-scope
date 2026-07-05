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

  const items = useMemo(() => master?.items ?? [], [master?.items])
  const totalQuestions = items.length
  const answered = useMemo(
    () => items.filter((q) => responses[String(q.id)] != null).length,
    [items, responses],
  )
  const complete = answered >= totalQuestions && totalQuestions > 0

  const labelMuted = 'text-xs text-[var(--ss-t2)]'
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
        <h2 className="text-base font-semibold text-[var(--ss-t1)]">{t('condition.prematch.title')}</h2>
        <p className={labelMuted}>{t('condition.prematch.intro')}</p>
      </div>

      <div className="sticky top-0 z-10 bg-[var(--ss-bg-app)] py-2">
        <div className="flex items-center gap-3">
          <div className="flex-1 h-2 bg-[var(--ss-surface-3)] rounded-ss-sm overflow-hidden">
            <div className="h-full bg-[var(--ss-brand)] transition-all duration-base ease-out" style={{ width: `${pct}%` }} />
          </div>
          <div className="text-xs whitespace-nowrap text-[var(--ss-t2)] ss-num">
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
        <div className="text-sm bg-[var(--ss-danger-bg)] text-[var(--ss-danger-text)] border border-[var(--ss-danger-border)] rounded-ss-md px-3 py-2">
          {errorMsg}
        </div>
      )}

      <div className="flex justify-end">
        <button
          onClick={handleSubmit}
          disabled={mut.isPending || !complete}
          className="px-4 py-2 bg-[var(--ss-brand)] hover:bg-[var(--ss-brand-hover)] disabled:opacity-50 text-white rounded-ss-md text-sm font-medium transition-colors duration-fast ease-out"
        >
          {mut.isPending ? '...' : t('condition.prematch.submit')}
        </button>
      </div>
    </div>
  )
}
