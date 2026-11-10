// 大会レベル別比較コンポーネント（棒グラフ + テーブル）
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { NoDataMessage } from '@/components/common/NoDataMessage'
import { BAR, getTooltipStyle, AXIS_TICK, AXIS_TICK_LIGHT } from '@/styles/colors'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { useAuth } from '@/hooks/useAuth'
import { AnalysisFilters, DEFAULT_FILTERS } from '@/types'
import { fmtPct } from '@/utils/format'

interface TournamentComparisonProps {
  playerId: number
  filters?: AnalysisFilters
}

interface LevelData {
  level: string
  match_count: number
  win_rate: number | null
  avg_rally_length: number | null
  sample_size: number
  // 試合数が少なく勝率が参考値のとき true (OpponentStats の n<3 灰色表示と同じ基準)
  insufficient?: boolean
}

// backend の insufficient を優先。無い古い応答は試合数 3 未満で判定する
function isLowSample(l: LevelData): boolean {
  return l.insufficient ?? l.match_count < 3
}

interface TournamentResponse {
  success: boolean
  data: { levels: LevelData[] }
  meta: {
    sample_size: number
    confidence: { level: string; stars: string; label: string }
  }
}

export function TournamentComparison({ playerId, filters = DEFAULT_FILTERS }: TournamentComparisonProps) {
  const { t } = useTranslation()
  const isLight = useIsLightMode()
  // 製品ルール: player には勝率を見せない。大会レベル別の試合数の比較に置き換える。
  const { role } = useAuth()
  const isPlayer = role === 'player'

  // 勝敗フィルタは渡さない。「課題のある試合」(負け) で絞ると全レベルの勝率が 0%、
  // 「勝ち」で絞ると 100% に固定され、大会レベルの比較として情報が無くなる。
  const resultFilterIgnored = filters.result !== 'all'
  const fp = {
    ...(filters.tournamentLevel ? { tournament_level: filters.tournamentLevel } : {}),
    ...(filters.dateFrom ? { date_from: filters.dateFrom } : {}),
    ...(filters.dateTo ? { date_to: filters.dateTo } : {}),
  }
  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-tournament-comparison', playerId, fp],
    queryFn: () =>
      apiGet<TournamentResponse>('/analysis/tournament_level_comparison', { player_id: playerId, ...fp }),
    enabled: !!playerId,
  })

  if (isLoading) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.loading')}</div>
  }

  const levels = resp?.data?.levels ?? []
  const sampleSize = resp?.meta?.sample_size ?? 0

  if (levels.length === 0) {
    return <NoDataMessage sampleSize={sampleSize} minRequired={1} unit="試合" />
  }

  // 棒は単色 (勝率のみを高さで表す)。大会重要度の coolwarm 配色は凡例が無く、赤が他画面の
  // 「失点/悪い」と衝突し、白に近い色はライトテーマで見えなかった。標本数は X 軸ラベルに併記する。
  const chartData = levels.map((l) => ({
    name: l.level,
    label: `${l.level} (${t('auto._shared.n_matches', { n: l.match_count })})`,
    win_rate: typeof l.win_rate === 'number' ? Math.round(l.win_rate * 100) : null,
    match_count: l.match_count,
  }))

  return (
    <div className="space-y-3">
      <ConfidenceBadge sampleSize={sampleSize} unit="matches" />
      {resultFilterIgnored && (
        <p className="text-[11px] text-gray-400" data-testid="tournament-result-filter-ignored">
          {t('analysis.tournament_comparison.result_filter_ignored')}
        </p>
      )}

      {/* 棒グラフ */}
      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={chartData} margin={{ top: 5, right: 16, left: 0, bottom: 5 }}>
          <XAxis dataKey="label" tick={{ fill: isLight ? AXIS_TICK_LIGHT : AXIS_TICK, fontSize: 11 }} />
          {isPlayer ? (
            <YAxis allowDecimals={false} tick={{ fill: isLight ? AXIS_TICK_LIGHT : AXIS_TICK, fontSize: 11 }} />
          ) : (
            <YAxis
              tick={{ fill: isLight ? AXIS_TICK_LIGHT : AXIS_TICK, fontSize: 11 }}
              domain={[0, 100]}
              tickFormatter={(v) => `${v}%`}
            />
          )}
          <Tooltip
            contentStyle={{ ...getTooltipStyle(isLight), borderRadius: 6 }}
            formatter={(value: number) => isPlayer
              ? [`${value}`, t('analysis.tournament_comparison.match_count')]
              : [`${value}%`, t('analysis.tournament_comparison.win_rate')]}
          />
          {isPlayer ? (
            <Bar dataKey="match_count" fill={BAR} radius={[3, 3, 0, 0]} name={t('analysis.tournament_comparison.match_count')} />
          ) : (
            <Bar dataKey="win_rate" fill={BAR} radius={[3, 3, 0, 0]} name={t('analysis.tournament_comparison.win_rate')} />
          )}
        </BarChart>
      </ResponsiveContainer>
      {!isPlayer && <p className="text-[11px] text-gray-400">{t('analysis.tournament_comparison.bar_note')}</p>}
      {!isPlayer && levels.some(isLowSample) && (
        <p className="text-[11px] text-gray-400">{t('analysis.tournament_comparison.low_sample_hint')}</p>
      )}

      {/* テーブル */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-gray-400 border-b border-gray-700">
              <th className="text-left py-1.5 pr-3">{t('analysis.tournament_comparison.level')}</th>
              <th className="text-center py-1.5 pr-3">{t('analysis.tournament_comparison.match_count')}</th>
              {!isPlayer && <th className="text-center py-1.5 pr-3">{t('analysis.tournament_comparison.win_rate')}</th>}
              <th className="text-right py-1.5 pr-2">{t('analysis.tournament_comparison.avg_rally')}</th>
            </tr>
          </thead>
          <tbody>
            {levels.map((l) => (
              <tr key={l.level} className="border-b border-gray-700/40 hover:bg-gray-700/20">
                <td className="py-1.5 pr-3 font-medium" style={{ color: isLight ? '#334155' : '#d1d5db' }}>
                  {l.level}
                </td>
                <td className="py-1.5 pr-3 text-center num-cell ss-num" style={{ color: isLight ? '#334155' : '#d1d5db' }}>{l.match_count}</td>
                {!isPlayer && (
                  <td
                    className="py-1.5 pr-3 text-center font-semibold num-cell ss-num"
                    style={{ color: isLowSample(l) ? (isLight ? '#64748b' : '#9ca3af') : (isLight ? '#334155' : '#d1d5db') }}
                  >
                    {fmtPct(l.win_rate)}
                  </td>
                )}
                <td className="py-1.5 pr-2 text-right num-cell ss-num" style={{ color: isLight ? '#334155' : '#d1d5db' }}>
                  {typeof l.avg_rally_length === 'number' ? l.avg_rally_length.toFixed(1) : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
