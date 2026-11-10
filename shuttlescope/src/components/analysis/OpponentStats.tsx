// 対戦相手別統計テーブルコンポーネント（アナリスト・コーチ向け）
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { RoleGuard } from '@/components/common/RoleGuard'
import { fmtPct } from '@/utils/format'

// 試合数がこれ未満の相手は勝率を強調色にせず「参考値」とする (n=1 の 0%/100% を成績として見せない)。
const MIN_MATCHES_FOR_RATE = 3

function rateClass(
  opp: { win_rate: number | null; match_count: number; insufficient?: boolean },
  strong: boolean,
): string {
  // backend の insufficient (試合数 < 3) を優先。無い古い応答は試合数で判定する
  const low = opp.insufficient ?? opp.match_count < MIN_MATCHES_FOR_RATE
  if (low || typeof opp.win_rate !== 'number') return 'text-gray-400'
  if (opp.win_rate >= 0.6) return strong ? 'text-blue-300 font-semibold' : 'text-blue-300'
  if (opp.win_rate <= 0.4) return 'text-red-300'
  return 'text-gray-300'
}

interface OpponentStatsProps {
  playerId: number
}

interface OpponentData {
  opponent_id: number
  opponent_name: string
  match_count: number
  win_rate: number | null
  avg_rally_length: number | null
  sample_size: number
  // 試合数が少なく勝率が参考値のとき true
  insufficient?: boolean
}

interface OpponentStatsResponse {
  success: boolean
  data: { opponents: OpponentData[] }
  meta: { sample_size: number; confidence: { level: string; stars: string; label: string } }
}

function OpponentTable({ playerId }: { playerId: number }) {
  const { t } = useTranslation()

  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-opponent-stats', playerId],
    queryFn: () =>
      apiGet<OpponentStatsResponse>('/analysis/opponent_stats', { player_id: playerId }),
    enabled: !!playerId,
  })

  if (isLoading) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.loading')}</div>
  }

  const opponents = resp?.data?.opponents ?? []
  const sampleSize = resp?.meta?.sample_size ?? 0

  if (opponents.length === 0) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.no_data')}</div>
  }

  const sorted = [...opponents].sort((a, b) => b.match_count - a.match_count)

  return (
    <div className="space-y-3">
      <ConfidenceBadge sampleSize={sampleSize} unit="rallies" />
      {sorted.some((o) => o.match_count < MIN_MATCHES_FOR_RATE) && (
        <p className="text-[11px] text-gray-400">{t('analysis.opponent_stats.low_sample_hint')}</p>
      )}

      {/* モバイル: カードリスト (md 未満)。情報量を維持しつつ縦並びで横スクロール回避 */}
      <ul className="md:hidden space-y-1.5">
        {sorted.map((opp) => (
          <li key={opp.opponent_id} className="rounded-ss-md border border-gray-700 bg-gray-800/40 p-2">
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-sm text-white font-medium truncate" title={opp.opponent_name}>
                {opp.opponent_name}
              </span>
              <span className={'text-sm font-semibold num-cell ss-num shrink-0 ' + rateClass(opp, false)}>
                {fmtPct(opp.win_rate)}
              </span>
            </div>
            <div className="flex justify-between text-[11px] text-gray-400 num-cell ss-num mt-0.5">
              <span className="inline-flex items-center gap-1">
                {t('analysis.opponent_stats.match_count')} {opp.match_count}
                <ConfidenceBadge sampleSize={opp.match_count} unit="matches" compact />
              </span>
              <span>{t('analysis.opponent_stats.avg_rally')} {typeof opp.avg_rally_length === 'number' ? opp.avg_rally_length.toFixed(1) : '—'}</span>
            </div>
          </li>
        ))}
      </ul>

      {/* デスクトップ: テーブル (md 以上)。長文相手名は cell-name-clip + title でフル表示 */}
      <div className="hidden md:block overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-gray-400 border-b border-gray-700">
              <th className="text-left py-1.5 pr-3">{t('analysis.opponent_stats.opponent')}</th>
              <th className="text-center py-1.5 pr-3">{t('analysis.opponent_stats.match_count')}</th>
              <th className="text-center py-1.5 pr-3">{t('analysis.opponent_stats.win_rate')}</th>
              <th className="text-right py-1.5 pr-2">{t('analysis.opponent_stats.avg_rally')}</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((opp) => (
              <tr
                key={opp.opponent_id}
                className="border-b border-gray-700/40 hover:bg-gray-700/20"
              >
                <td className="py-1.5 pr-3 text-white font-medium">
                  <span className="cell-name-clip" title={opp.opponent_name}>{opp.opponent_name}</span>
                </td>
                <td className="py-1.5 pr-3 text-center text-gray-300 num-cell ss-num">
                  <span className="inline-flex items-center gap-1">
                    {opp.match_count}
                    <ConfidenceBadge sampleSize={opp.match_count} unit="matches" compact />
                  </span>
                </td>
                <td className="py-1.5 pr-3 text-center">
                  <span className={'num-cell ss-num ' + rateClass(opp, true)}>
                    {fmtPct(opp.win_rate)}
                  </span>
                </td>
                <td className="py-1.5 pr-2 text-right text-gray-300 num-cell ss-num">{typeof opp.avg_rally_length === 'number' ? opp.avg_rally_length.toFixed(1) : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export function OpponentStats({ playerId }: OpponentStatsProps) {
  const { t } = useTranslation()
  return (
    <RoleGuard
      allowedRoles={['analyst', 'coach']}
      fallback={
        <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.restricted')}</div>
      }
    >
      <OpponentTable playerId={playerId} />
    </RoleGuard>
  )
}
