// Phase 2: ペアモード合算ビュー（pair_combined エンドポイント）
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { AnalysisFilters, DEFAULT_FILTERS } from '@/types'
import { WIN, LOSS } from '@/styles/colors'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { PartnerTimeline } from './PartnerTimeline'

interface PairCombinedViewProps {
  playerAId: number
  playerBId: number
  playerAName?: string
  playerBName?: string
  filters?: AnalysisFilters
}

interface PairCombinedResponse {
  success: boolean
  data: {
    pair_win_rate: number | null
    pair_match_count: number
    shared_matches: number[]
    stroke_share: { player_a: number; player_b: number }
    common_loss_pattern: string | null
    common_win_shot: string | null
  }
  meta: { sample_size: number; confidence: { level: string; stars: string; label: string } }
}

const SHOT_JA: Record<string, string> = {
  smash: 'スマッシュ', clear: 'クリア', drop: 'ドロップ', net: 'ネット',
  drive: 'ドライブ', lob: 'ロブ', serve: 'サーブ', push: 'プッシュ',
  lift: 'リフト', hair_pin: 'ヘアピン', hairpin: 'ヘアピン', flick: 'フリック',
  net_shot: 'ネットショット', push_rush: 'プッシュ/ラッシュ', defensive: 'ディフェンス',
  cross_net: 'クロスネット',
}
function shotJa(s: string | null) {
  if (!s) return '—'
  return SHOT_JA[s.toLowerCase()] ?? s
}

export function PairCombinedView({
  playerAId, playerBId, playerAName = 'A', playerBName = 'B', filters = DEFAULT_FILTERS,
}: PairCombinedViewProps) {
  const { t } = useTranslation()
  const isLight = useIsLightMode()

  const fp = {
    player_a_id: playerAId,
    player_b_id: playerBId,
    ...(filters.result !== 'all' ? { result: filters.result } : {}),
    ...(filters.tournamentLevel ? { tournament_level: filters.tournamentLevel } : {}),
    ...(filters.dateFrom ? { date_from: filters.dateFrom } : {}),
    ...(filters.dateTo ? { date_to: filters.dateTo } : {}),
  }

  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-pair-combined', playerAId, playerBId, filters],
    queryFn: () => apiGet<PairCombinedResponse>('/analysis/pair_combined', fp),
    enabled: !!playerAId && !!playerBId,
  })

  if (isLoading) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.loading')}</div>
  }

  const sampleSize = resp?.meta?.sample_size ?? 0
  const d = resp?.data

  if (!d || d.pair_match_count === 0) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.no_data')}</div>
  }

  const winRate = d.pair_win_rate
  const winColor = winRate != null && winRate >= 0.5 ? WIN : LOSS

  // ライトモード対応カラー定義
  const labelColor = isLight ? '#475569' : '#9ca3af'
  const nameColor  = isLight ? '#1e293b' : '#d1d5db'
  const pctColor   = isLight ? '#64748b' : '#6b7280'
  const trackBg    = isLight ? '#e2e8f0' : '#374151'
  const cardBg     = isLight ? '#f8fafc' : '#1f2937'
  const cardBorder = isLight ? '#e2e8f0' : '#374151'

  return (
    <div className="space-y-4">
      <ConfidenceBadge sampleSize={sampleSize} />

      {/* ペア勝率 + 試合数 */}
      <div className="flex gap-3">
        <div
          className="flex-1 rounded-lg p-3 text-center"
          style={{ backgroundColor: cardBg, border: `1px solid ${cardBorder}` }}
        >
          <p className="text-xs" style={{ color: labelColor }}>ペア勝率</p>
          <p className="text-2xl font-bold mt-0.5" style={{ color: winColor }}>
            {winRate != null ? `${(winRate * 100).toFixed(0)}%` : '—'}
          </p>
        </div>
        <div
          className="flex-1 rounded-lg p-3 text-center"
          style={{ backgroundColor: cardBg, border: `1px solid ${cardBorder}` }}
        >
          <p className="text-xs" style={{ color: labelColor }}>共通出場試合</p>
          <p className="text-2xl font-bold mt-0.5" style={{ color: isLight ? '#1e293b' : '#e2e8f0' }}>
            {d.pair_match_count}
          </p>
        </div>
      </div>

      {/* ストローク分担 */}
      <div>
        <p className="text-xs mb-1" style={{ color: labelColor }}>ストローク分担</p>
        <div className="flex items-center gap-2">
          <span className="text-xs w-20 truncate" style={{ color: nameColor }}>{playerAName}</span>
          <div className="flex-1 rounded-full h-2 overflow-hidden" style={{ backgroundColor: trackBg }}>
            <div
              className="h-2 rounded-full transition-all"
              style={{ width: `${(d.stroke_share.player_a * 100).toFixed(0)}%`, backgroundColor: WIN }}
            />
          </div>
          <span className="text-xs w-20 text-right truncate" style={{ color: nameColor }}>{playerBName}</span>
        </div>
        <div className="flex justify-between mt-0.5">
          <span className="text-[10px]" style={{ color: pctColor }}>{(d.stroke_share.player_a * 100).toFixed(0)}%</span>
          <span className="text-[10px]" style={{ color: pctColor }}>{(d.stroke_share.player_b * 100).toFixed(0)}%</span>
        </div>
      </div>

      {/* 共通の有効ショット / 失点ショット */}
      <div className="grid grid-cols-2 gap-3">
        <div
          className="rounded p-2.5"
          style={{ backgroundColor: 'rgba(59,130,246,0.08)', border: `1px solid ${WIN}` }}
        >
          <p className="text-[10px] mb-1" style={{ color: labelColor }}>共通の得点ショット</p>
          <p className="text-sm font-semibold" style={{ color: WIN }}>{shotJa(d.common_win_shot)}</p>
        </div>
        <div
          className="rounded p-2.5"
          style={{ backgroundColor: 'rgba(239,68,68,0.08)', border: `1px solid ${LOSS}` }}
        >
          <p className="text-[10px] mb-1" style={{ color: labelColor }}>共通の失点ショット</p>
          <p className="text-sm font-semibold" style={{ color: LOSS }}>{shotJa(d.common_loss_pattern)}</p>
        </div>
      </div>

      {/* ペア別勝率推移 */}
      <div>
        <p className="text-xs mb-2" style={{ color: labelColor }}>ペア勝率推移</p>
        <PartnerTimeline
          playerId={playerAId}
          partnerId={playerBId}
          partnerName={playerBName}
        />
      </div>
    </div>
  )
}
