// セット間速報レポートコンポーネント（ベイズ推定による推定勝率）
//
// Design Language v1.2 準拠 (2026-05-19):
//   - カード bg は無彩色 (N_GRAY)
//   - 数値の符号 (≥0.55 / ≤0.45) で A_GOOD / B_BAD 文字色のみ
//   - セット行は背景無彩色、クリック可能なら左罫線で affordance
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { A_GOOD, B_BAD, N_GRAY } from '@/styles/colors'

interface IntervalReportProps {
  matchId: number
  completedSet: number
  /** セット行クリック時の callback。セットの詳細モーダル (SetIntervalSummary) を開く用途。
   *  未指定なら行はクリック不可。 */
  onSetClick?: (setNum: number) => void
}

interface SetReport {
  set_num: number
  rally_count: number
  wins: number
  win_rate_raw: number
  posterior_mean: number
  ci_low: number
  ci_high: number
}

interface WinEstimate {
  mean: number
  ci_low: number
  ci_high: number
}

interface IntervalReportData {
  match_id: number
  completed_set_num: number
  sets: SetReport[]
  current_win_estimate: WinEstimate | null
  prior: { alpha: number; beta: number }
}

interface IntervalReportResponse {
  success: boolean
  data: IntervalReportData
  meta: { sample_size: number; confidence: { level: string; stars: string; label: string } }
}

export function IntervalReport({ matchId, completedSet, onSetClick }: IntervalReportProps) {
  const { t } = useTranslation()

  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-interval-report', matchId, completedSet],
    queryFn: () =>
      apiGet<IntervalReportResponse>('/analysis/interval_report', {
        match_id: matchId,
        completed_set_num: completedSet,
      }),
    enabled: !!matchId,
  })

  if (isLoading) {
    return <div className="text-[var(--ss-t3)] text-sm py-4 text-center">{t('analysis.loading')}</div>
  }

  if (!resp?.success || !resp.data) {
    return <div className="text-[var(--ss-t3)] text-sm py-4 text-center">{t('analysis.no_data')}</div>
  }

  const data = resp.data
  const sampleSize = resp?.meta?.sample_size ?? 0
  const currentEst = data.current_win_estimate

  return (
    <div className="space-y-3">
      <ConfidenceBadge sampleSize={sampleSize} />

      {/* 現在の推定勝率 — 無彩色カード、数値の符号のみ A/B 色 */}
      {currentEst && (() => {
        const winColor =
          currentEst.mean >= 0.55 ? A_GOOD
          : currentEst.mean <= 0.45 ? B_BAD
          : 'var(--ss-t3)'
        return (
          <div
            className="rounded-ss-lg p-3 text-center bg-[var(--ss-surface-1)] border border-[var(--ss-border)]"
          >
            <p className="text-[10px] tracking-[0.18em] uppercase mb-1 text-[var(--ss-t3)]">
              {t('analysis.interval_report.current_estimate')}
            </p>
            <p className="text-2xl font-bold ss-num" style={{ color: winColor }}>
              {(currentEst.mean * 100).toFixed(1)}%
            </p>
            <p className="text-[10px] mt-1 font-mono ss-num text-[var(--ss-t3)]">
              {t('auto.IntervalReport.ci_interval', { lo: (currentEst.ci_low * 100).toFixed(1), hi: (currentEst.ci_high * 100).toFixed(1) })}
            </p>
          </div>
        )
      })()}

      {/* セットごとの詳細 */}
      {data.sets.length > 0 && (
        <div className="space-y-2">
          {data.sets.map((setReport) => {
            const clickable = !!onSetClick
            const Inner = (
              <>
                <div>
                  <span className="text-sm font-medium text-[var(--ss-t1)]">
                    {t('analysis.interval_report.set')} {setReport.set_num}
                  </span>
                  <span className="text-xs text-[var(--ss-t3)] ml-2">
                    {setReport.wins}/{t('auto._shared.n_rallies', { n: setReport.rally_count })}
                  </span>
                </div>
                <div className="text-right flex items-center gap-2">
                  <div>
                    <p className="text-sm font-semibold ss-num text-[var(--ss-t1)]">
                      {(setReport.posterior_mean * 100).toFixed(1)}%
                    </p>
                    <p className="text-[10px] ss-num text-[var(--ss-t3)]">
                      [{(setReport.ci_low * 100).toFixed(1)}, {(setReport.ci_high * 100).toFixed(1)}]
                    </p>
                  </div>
                  {clickable && <span className="text-[var(--ss-brand)] text-xs">{t('auto.IntervalReport.k1')}</span>}
                </div>
              </>
            )
            return clickable ? (
              <button
                key={setReport.set_num}
                type="button"
                onClick={() => onSetClick!(setReport.set_num)}
                className="w-full bg-[var(--ss-surface-2)] hover:bg-[var(--ss-surface-3)] rounded-ss-md p-2.5 flex items-center justify-between text-left transition-colors duration-base ease-out"
                title={t('auto.IntervalReport.k2')}
              >
                {Inner}
              </button>
            ) : (
              <div
                key={setReport.set_num}
                className="bg-[var(--ss-surface-2)] rounded-ss-md p-2.5 flex items-center justify-between"
              >
                {Inner}
              </div>
            )
          })}
        </div>
      )}

      {data.sets.length === 0 && (
        <p className="text-[var(--ss-t3)] text-sm text-center py-2">{t('analysis.no_data')}</p>
      )}

      <p className="text-[10px] text-[var(--ss-t3)] text-center">
        {t('auto.IntervalReport.bayes_note')}
      </p>
    </div>
  )
}
