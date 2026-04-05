// セット間速報レポートコンポーネント（ベイズ推定による推定勝率）
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'

interface IntervalReportProps {
  matchId: number
  completedSet: number
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

export function IntervalReport({ matchId, completedSet }: IntervalReportProps) {
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
    return <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.loading')}</div>
  }

  if (!resp?.success || !resp.data) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.no_data')}</div>
  }

  const data = resp.data
  const sampleSize = resp?.meta?.sample_size ?? 0
  const currentEst = data.current_win_estimate

  return (
    <div className="space-y-3">
      <ConfidenceBadge sampleSize={sampleSize} />

      {/* 現在の推定勝率 */}
      {currentEst && (
        <div className="bg-blue-900/30 border border-blue-700 rounded-lg p-3 text-center">
          <p className="text-xs text-blue-300 mb-1">{t('analysis.interval_report.current_estimate')}</p>
          <p className="text-2xl font-bold text-blue-400">
            {(currentEst.mean * 100).toFixed(1)}%
          </p>
          <p className="text-xs text-gray-400 mt-1">
            95%CI: [{(currentEst.ci_low * 100).toFixed(1)}%, {(currentEst.ci_high * 100).toFixed(1)}%]
          </p>
        </div>
      )}

      {/* セットごとの詳細 */}
      {data.sets.length > 0 && (
        <div className="space-y-2">
          {data.sets.map((setReport) => (
            <div
              key={setReport.set_num}
              className="bg-gray-700/50 rounded-lg p-2.5 flex items-center justify-between"
            >
              <div>
                <span className="text-sm font-medium text-white">
                  {t('analysis.interval_report.set')} {setReport.set_num}
                </span>
                <span className="text-xs text-gray-400 ml-2">
                  {setReport.wins}/{setReport.rally_count}ラリー
                </span>
              </div>
              <div className="text-right">
                <p className="text-sm font-semibold text-white">
                  {(setReport.posterior_mean * 100).toFixed(1)}%
                </p>
                <p className="text-[10px] text-gray-500">
                  [{(setReport.ci_low * 100).toFixed(1)}, {(setReport.ci_high * 100).toFixed(1)}]
                </p>
              </div>
            </div>
          ))}
        </div>
      )}

      {data.sets.length === 0 && (
        <p className="text-gray-500 text-sm text-center py-2">{t('analysis.no_data')}</p>
      )}

      <p className="text-[10px] text-gray-600 text-center">
        ※ ベイズ推定による勝率推定。このデータは相関を示すものであり、因果関係を示すものではありません。
      </p>
    </div>
  )
}
