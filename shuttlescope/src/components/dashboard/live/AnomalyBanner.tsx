/**
 * AnomalyBanner — "今、ふだんと違う" 検知バナー (coach 向け)
 *
 * - GET /api/analysis/live_anomaly?player_id&match_id&window=5
 * - anomaly=true の時のみ表示、30s ごとに refetch
 * - dismissible (localStorage に test 中の dismiss は保持しない / セッション中のみ)
 * - confidence chip + 詳細モーダル (diverging shot types)
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiGet } from '@/api/client'
import { MIcon } from '@/components/common/MIcon'

interface AnomalyResponse {
  anomaly: boolean
  headline_ja?: string
  headline_en?: string
  confidence?: number
  evidence?: {
    kl?: number
    threshold?: number
    window_rallies?: number
    recent_strokes?: number
    baseline_strokes?: number
    primary_shot?: string
    shot_diffs_pp?: Array<{ shot_type: string; delta_pp: number; recent_n: number }>
  }
}

interface Props {
  playerId: number
  matchId: number
  windowSize?: number
}

export function AnomalyBanner({ playerId, matchId, windowSize = 5 }: Props) {
  const { t, i18n } = useTranslation()
  const [dismissed, setDismissed] = useState(false)
  const [detailOpen, setDetailOpen] = useState(false)

  const { data } = useQuery<AnomalyResponse>({
    queryKey: ['live-anomaly', playerId, matchId, windowSize],
    queryFn: () =>
      apiGet<AnomalyResponse>('/analysis/live_anomaly', {
        player_id: playerId,
        match_id: matchId,
        window: windowSize,
      }),
    refetchInterval: 30_000,
    enabled: !!playerId && !!matchId,
  })

  if (!data || !data.anomaly || dismissed) return null

  const headline = i18n.language?.startsWith('en')
    ? (data.headline_en ?? data.headline_ja ?? '')
    : (data.headline_ja ?? data.headline_en ?? '')
  const confPct = Math.round((data.confidence ?? 0) * 100)

  return (
    <div
      data-tutorial="dashboard.anomaly"
      className="rounded-ss-lg border border-[var(--ss-warning-border)] bg-[var(--ss-warning-bg)] text-[var(--ss-warning-text)] p-3 flex items-start gap-3"
    >
      <MIcon name="warning" size={24} aria-hidden />
      <div className="flex-1">
        <div className="font-semibold text-sm">{t('auto.AnomalyBanner.title')}</div>
        <div className="text-sm mt-1 whitespace-pre-wrap">{headline}</div>
        <div className="mt-2 flex items-center gap-2 text-xs">
          <span className="inline-flex items-center rounded-ss-sm border border-[var(--ss-warning-border)] bg-[var(--ss-surface-1)] px-2 py-0.5 font-medium ss-num">
            {t('auto.AnomalyBanner.confidence', { pct: confPct })}
          </span>
          <button
            type="button"
            onClick={() => setDetailOpen(true)}
            className="underline hover:no-underline"
          >
            {t('auto.AnomalyBanner.detail')}
          </button>
        </div>
      </div>
      <button
        type="button"
        aria-label={t('auto.AnomalyBanner.dismiss')}
        onClick={() => setDismissed(true)}
        className="text-[var(--ss-warning-text)] hover:opacity-70 transition-opacity duration-fast ease-out px-2"
      >
        ×
      </button>

      {detailOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--ss-bg-overlay)]"
          onClick={() => setDetailOpen(false)}
        >
          <div
            className="bg-[var(--ss-surface-1)] text-[var(--ss-t1)] border border-[var(--ss-border)] rounded-ss-lg p-4 max-w-md w-[90%] shadow-pop"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="font-semibold mb-2">{t('auto.AnomalyBanner.detail_title')}</div>
            <div className="text-xs mb-2 text-[var(--ss-t3)] ss-num">
              KL={data.evidence?.kl ?? '-'} / threshold={data.evidence?.threshold ?? '-'} / N={data.evidence?.recent_strokes ?? 0}
            </div>
            <ul className="text-sm space-y-1">
              {(data.evidence?.shot_diffs_pp ?? []).map((d) => (
                <li key={d.shot_type} className="flex justify-between">
                  <span>{d.shot_type}</span>
                  <span className={`ss-num ${d.delta_pp >= 0 ? 'text-[var(--ss-warning-text)]' : 'text-[var(--ss-brand)]'}`}>
                    {d.delta_pp >= 0 ? '+' : ''}
                    {d.delta_pp}pp (N={d.recent_n})
                  </span>
                </li>
              ))}
            </ul>
            <button
              type="button"
              onClick={() => setDetailOpen(false)}
              className="mt-3 px-3 py-1 rounded-ss-md bg-[var(--ss-surface-2)] hover:bg-[var(--ss-surface-3)] transition-colors duration-fast ease-out text-sm"
            >
              {t('auto.AnomalyBanner.close')}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
