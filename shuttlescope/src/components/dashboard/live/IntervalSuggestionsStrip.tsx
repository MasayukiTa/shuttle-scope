/**
 * IntervalSuggestionsStrip — インターバル戦術提案 (coach 向け Top 3)
 *
 * GET /api/analysis/live_suggestions?player_id&match_id
 * 表示条件: setScore >= 11 もしくは rallyCountSinceLast >= 60 もしくは show=true
 * 「今すぐ提案」ボタンで手動 fetch も可。
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiGet } from '@/api/client'

interface SuggestionItem {
  id: string
  headline_ja: string
  headline_en: string
  confidence: number
  evidence_path?: string
}

interface SuggestionsResponse {
  items: SuggestionItem[]
  meta?: Record<string, unknown>
}

interface Props {
  playerId: number
  matchId: number
  /** 現セットの最大スコア (11 で自動表示) */
  setScore?: number
  /** 前回提示からのラリー数 (60 で自動表示) */
  rallyCountSinceLast?: number
}

export function IntervalSuggestionsStrip({
  playerId,
  matchId,
  setScore = 0,
  rallyCountSinceLast = 0,
}: Props) {
  const { t, i18n } = useTranslation()
  const [forceShow, setForceShow] = useState(false)

  const autoShow = setScore === 11 || rallyCountSinceLast >= 60
  const visible = autoShow || forceShow

  const { data, isFetching, refetch } = useQuery<SuggestionsResponse>({
    queryKey: ['live-suggestions', playerId, matchId],
    queryFn: () =>
      apiGet<SuggestionsResponse>('/analysis/live_suggestions', {
        player_id: playerId,
        match_id: matchId,
      }),
    enabled: !!playerId && !!matchId && visible,
    staleTime: 30_000,
  })

  return (
    <div
      data-tutorial="dashboard.interval_suggestions"
      className="rounded-lg border border-blue-400 bg-blue-50 text-blue-900 p-3"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="font-semibold text-sm">
          {t('auto.IntervalSuggestionsStrip.title')}
        </div>
        <button
          type="button"
          onClick={() => {
            setForceShow(true)
            void refetch()
          }}
          className="text-xs px-3 py-1 rounded bg-blue-600 text-white hover:bg-blue-700"
        >
          {t('auto.IntervalSuggestionsStrip.refresh_now')}
        </button>
      </div>
      {!visible && (
        <div className="text-xs text-blue-800 mt-2">
          {t('auto.IntervalSuggestionsStrip.idle_hint')}
        </div>
      )}
      {visible && isFetching && !data && (
        <div className="text-xs mt-2">{t('auto.IntervalSuggestionsStrip.loading')}</div>
      )}
      {visible && data && data.items.length === 0 && (
        <div className="text-xs mt-2">{t('auto.IntervalSuggestionsStrip.empty')}</div>
      )}
      {visible && data && data.items.length > 0 && (
        <ol className="mt-2 space-y-2">
          {data.items.map((it, idx) => {
            const headline = i18n.language?.startsWith('en') ? it.headline_en : it.headline_ja
            const confPct = Math.round(it.confidence * 100)
            return (
              <li key={it.id} className="flex items-start gap-2 text-sm">
                <span className="font-bold w-5">{idx + 1}.</span>
                <div className="flex-1">
                  <div>{headline}</div>
                  <div className="text-xs mt-1 flex items-center gap-2">
                    <span className="inline-flex items-center rounded border border-blue-500 bg-white px-2 py-0.5 font-medium text-blue-800">
                      {t('auto.IntervalSuggestionsStrip.confidence', { pct: confPct })}
                    </span>
                    {it.evidence_path && (
                      <span className="text-blue-700 text-xs">{it.evidence_path}</span>
                    )}
                  </div>
                </div>
              </li>
            )
          })}
        </ol>
      )}
    </div>
  )
}
