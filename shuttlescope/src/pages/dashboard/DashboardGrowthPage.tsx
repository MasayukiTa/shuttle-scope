import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ErrorBoundary } from '@/components/common/ErrorBoundary'
import { AnalysisFilters, Player } from '@/types'
import { GrowthJudgmentCard } from '@/components/analysis/GrowthJudgmentCard'
import { GrowthTimeline } from '@/components/analysis/GrowthTimeline'
import { PairCombinedView } from '@/components/analysis/PairCombinedView'
import { useCardTheme } from '@/hooks/useCardTheme'

interface Props {
  playerId: number
  filters: AnalysisFilters
  sortedPlayers: Player[]
}

export function DashboardGrowthPage({ playerId, filters, sortedPlayers }: Props) {
  const { t } = useTranslation()
  const [pairMode, setPairMode] = useState(false)
  const [partnerPlayerId, setPartnerPlayerId] = useState<number | null>(null)
  const { card, textHeading, textSecondary, textMuted, isLight } = useCardTheme()

  const toggleClass = pairMode ? 'bg-blue-500' : (isLight ? 'bg-gray-300' : 'bg-gray-600')
  const selectClass = isLight
    ? 'bg-white border border-gray-300 text-gray-700 text-xs rounded px-2 py-1'
    : 'bg-gray-700 border border-gray-600 text-white text-xs rounded px-2 py-1'

  return (
    <div className="space-y-5">
      {/* ペアモードトグル（is_target 選手が2人以上いる場合のみ表示） */}
      {sortedPlayers.filter((p) => p.is_target).length >= 2 && (
        <div className={`flex items-center gap-3 ${card} rounded-lg px-4 py-3`}>
          <span className={`text-xs ${textSecondary}`}>{t('analysis.growth.pair_mode')}</span>
          <button
            onClick={() => { setPairMode((v) => !v); setPartnerPlayerId(null) }}
            className={`relative w-10 h-5 rounded-full transition-colors ${toggleClass}`}
          >
            <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${pairMode ? 'translate-x-5' : ''}`} />
          </button>
          {pairMode && (
            <select
              className={selectClass}
              value={partnerPlayerId ?? ''}
              onChange={(e) => setPartnerPlayerId(e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">{t('analysis.growth.pair_select_b')}</option>
              {sortedPlayers
                .filter((p) => p.is_target && p.id !== playerId)
                .map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
            </select>
          )}
        </div>
      )}

      {/* 成長判定カード */}
      <ErrorBoundary>
        <div className={`${card} rounded-lg p-4`}>
          <p className={`text-sm font-semibold mb-3 ${textHeading}`}>{t('analysis.growth.judgment_label')}</p>
          <GrowthJudgmentCard playerId={playerId} />
        </div>
      </ErrorBoundary>

      {/* 勝率推移 */}
      <ErrorBoundary>
        <div className={`${card} rounded-lg p-4`}>
          <p className={`text-xs font-semibold mb-2 ${textMuted}`}>{t('analysis.growth.win_rate_label')}</p>
          <GrowthTimeline
            playerId={playerId}
            playerName={sortedPlayers.find((p) => p.id === playerId)?.name}
            metric="win_rate"
            partnerPlayerId={pairMode ? partnerPlayerId : null}
            partnerName={sortedPlayers.find((p) => p.id === partnerPlayerId)?.name}
          />
        </div>
      </ErrorBoundary>

      {/* サーブ勝率推移 */}
      <ErrorBoundary>
        <div className={`${card} rounded-lg p-4`}>
          <p className={`text-xs font-semibold mb-2 ${textMuted}`}>{t('analysis.growth.serve_win_rate_label')}</p>
          <GrowthTimeline
            playerId={playerId}
            playerName={sortedPlayers.find((p) => p.id === playerId)?.name}
            metric="serve_win_rate"
            partnerPlayerId={pairMode ? partnerPlayerId : null}
            partnerName={sortedPlayers.find((p) => p.id === partnerPlayerId)?.name}
          />
        </div>
      </ErrorBoundary>

      {/* ペアモード: PairCombinedView */}
      {pairMode && partnerPlayerId && (
        <ErrorBoundary>
          <div className={`${card} rounded-lg p-4`}>
            <p className={`text-sm font-semibold mb-3 ${textHeading}`}>{t('analysis.growth.pair_combined_title')}</p>
            <PairCombinedView
              playerAId={playerId}
              playerBId={partnerPlayerId}
              playerAName={sortedPlayers.find((p) => p.id === playerId)?.name}
              playerBName={sortedPlayers.find((p) => p.id === partnerPlayerId)?.name}
              filters={filters}
            />
          </div>
        </ErrorBoundary>
      )}
    </div>
  )
}
