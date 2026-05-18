// ペアシナジースコアカード（アナリスト・コーチ向け）
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { NoDataMessage } from '@/components/common/NoDataMessage'
import { RoleGuard } from '@/components/common/RoleGuard'
import { perfColor, WIN, LOSS } from '@/styles/colors'
import { useTranslation } from 'react-i18next'

interface PairSynergyCardProps {
  playerId: number
}

interface PairEntry {
  partner_id: number
  partner_name: string
  match_count: number
  win_rate: number
  synergy_score: number
  avg_rally_length: number
  stroke_share: number
}

interface Response {
  success: boolean
  data: {
    player_avg_win_rate: number
    pairs: PairEntry[]
  }
  meta: { sample_size: number; confidence: { level: string; stars: string; label: string } }
}

function SynergyBar({ score }: { score: number }) {
  const { t } = useTranslation()

  const MAX = 0.5
  const pct = Math.min(Math.abs(score) / MAX * 50, 50)
  const positive = score >= 0
  return (
    <div className="flex items-center gap-1 w-32">
      <div className="flex-1 flex justify-end">
        {!positive && (
          <div
            className="h-3 rounded-l"
            style={{ width: `${pct}%`, backgroundColor: LOSS, opacity: 0.8 }}
          />
        )}
      </div>
      <div className="w-px h-3 bg-gray-500" />
      <div className="flex-1">
        {positive && (
          <div
            className="h-3 rounded-r"
            style={{ width: `${pct}%`, backgroundColor: WIN, opacity: 0.8 }}
          />
        )}
      </div>
    </div>
  )
}

function Inner({ playerId }: { playerId: number }) {
  const { t } = useTranslation()

  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-pair-synergy', playerId],
    queryFn: () => apiGet<Response>('/analysis/pair_synergy', { player_id: playerId }),
    enabled: !!playerId,
  })

  if (isLoading) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('auto.PairSynergyCard.k1')}</div>
  }

  const pairs = resp?.data?.pairs ?? []
  const avgWr = resp?.data?.player_avg_win_rate ?? 0
  const sampleSize = resp?.meta?.sample_size ?? 0

  if (pairs.length === 0) {
    return <NoDataMessage sampleSize={sampleSize} minRequired={3} unit="試合" />
  }

  return (
    <div className="space-y-3">
      <ConfidenceBadge sampleSize={sampleSize} />
      <p className="text-xs text-gray-400">
        全試合平均勝率: <span className="font-mono text-gray-200">{Math.round(avgWr * 100)}%</span>
      </p>

      <div className="space-y-2">
        {pairs.map(p => (
          <div key={p.partner_id} className="bg-gray-750 rounded p-3 border border-gray-700">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium text-gray-200">{p.partner_name}</span>
              <span className="text-xs text-gray-400">{p.match_count}試合</span>
            </div>
            <div className="flex items-center gap-3 text-xs">
              <div className="flex items-center gap-1">
                <span className="text-gray-400">{t('auto.PairSynergyCard.k2')}</span>
                <span
                  className="font-mono font-semibold"
                  style={{ color: perfColor(p.win_rate) }}
                >
                  {Math.round(p.win_rate * 100)}%
                </span>
              </div>
              <div className="flex items-center gap-1">
                <span className="text-gray-400">{t('auto.PairSynergyCard.k3')}</span>
                <SynergyBar score={p.synergy_score} />
                <span
                  className="font-mono text-xs"
                  style={{ color: p.synergy_score >= 0 ? WIN : LOSS }}
                >
                  {p.synergy_score >= 0 ? '+' : ''}{Math.round(p.synergy_score * 100)}%
                </span>
              </div>
            </div>
            <div className="flex gap-4 mt-1.5 text-xs text-gray-500">
              <span>平均ラリー長: {p.avg_rally_length}球</span>
              <span>打球分担: {Math.round(p.stroke_share * 100)}%</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export function PairSynergyCard({ playerId }: PairSynergyCardProps) {
  const { t } = useTranslation()

  return (
    <RoleGuard allowedRoles={['analyst', 'coach']}>
      <div className="bg-gray-800 rounded-lg p-4">
        <h3 className="text-sm font-semibold text-gray-200 mb-3">{t('auto.PairSynergyCard.k4')}</h3>
        <Inner playerId={playerId} />
      </div>
    </RoleGuard>
  )
}
