import { useTranslation } from 'react-i18next'
import { ErrorBoundary } from '@/components/common/ErrorBoundary'
import { AnalysisFilters } from '@/types'
import { PreLossPatterns } from '@/components/analysis/PreLossPatterns'
import { PreWinPatterns } from '@/components/analysis/PreWinPatterns'
import { EffectiveDistributionMap } from '@/components/analysis/EffectiveDistributionMap'
import { ReceivedVulnerabilityMap } from '@/components/analysis/ReceivedVulnerabilityMap'
import { ScoreProgression } from '@/components/analysis/ScoreProgression'
import { SetComparison } from '@/components/analysis/SetComparison'
import { RallySequencePatterns } from '@/components/analysis/RallySequencePatterns'
import { SearchableSelect } from '@/components/common/SearchableSelect'
import { useState, useCallback } from 'react'
import { SetIntervalSummary } from '@/components/analysis/SetIntervalSummary'

interface MatchSummary {
  match_id: number
  opponent: string
  tournament: string
  tournament_level: string
  date: string | null
  result: 'win' | 'loss' | string | null
  rally_count: number
  format: string
  set_count: number
  set_scores: { set_num: number; score_player: number; score_opponent: number; won: boolean }[]
}

interface Props {
  playerId: number
  filters: AnalysisFilters
  matches: MatchSummary[]
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h2 className="text-sm font-semibold text-gray-300 mb-0">{children}</h2>
}

export function DashboardReviewPage({ playerId, filters, matches }: Props) {
  const { t } = useTranslation()
  const [selectedMatchId, setSelectedMatchId] = useState<number | null>(null)
  const [pointAnalysis, setPointAnalysis] = useState<{
    setId: number; setNum: number; rallyNum: number; scoreA: number; scoreB: number
  } | null>(null)

  const handleSetPointClick = useCallback((
    setId: number, setNum: number, rallyNum: number, scoreA: number, scoreB: number
  ) => {
    setPointAnalysis({ setId, setNum, rallyNum, scoreA, scoreB })
  }, [])

  const matchOptions = matches.map((m) => ({
    value: m.match_id,
    label: `${m.date ?? '日付不明'} vs ${m.opponent}`,
    suffix: m.result === 'win' ? '勝' : '負',
    searchText: `${m.date ?? ''} ${m.opponent} ${m.tournament}`,
  }))

  return (
    <div className="space-y-5">
      {/* 推奨レビュー順序ガイド */}
      <div className="bg-gray-800 border border-gray-700 rounded-lg px-4 py-3">
        <p className="text-xs font-semibold text-gray-300 mb-2">
          {t('analysis.review.guide_title', '推奨レビュー順序')}
        </p>
        <ol className="flex flex-wrap gap-x-4 gap-y-1">
          {[
            t('analysis.review.guide_step1', '① 受け側の弱点・有効配球を確認'),
            t('analysis.review.guide_step2', '② 失点・得点前パターンを比較'),
            t('analysis.review.guide_step3', '③ セット別パフォーマンスで変化点を特定'),
            t('analysis.review.guide_step4', '④ ラリーシーケンスで繰り返しパターンを深掘り'),
          ].map((step) => (
            <li key={step} className="text-[11px] text-gray-400">{step}</li>
          ))}
        </ol>
      </div>

      {/* STEP 1: 弱点・有効配球マップ */}
      <ErrorBoundary>
        <div>
          <p className="text-[10px] text-gray-500 font-semibold uppercase tracking-wider mb-2 pl-1">
            {t('analysis.review.section_maps', 'STEP 1 — 弱点・配球マップ')}
          </p>
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
            <div className="bg-gray-800 rounded-lg p-4">
              <SectionTitle>{t('analysis.review.vulnerability_map')}</SectionTitle>
              <p className="text-xs text-gray-500 mb-3">{t('analysis.review.vulnerability_subtitle')}</p>
              <ReceivedVulnerabilityMap playerId={playerId} filters={filters} />
            </div>
            <div className="bg-gray-800 rounded-lg p-4">
              <SectionTitle>{t('analysis.review.effective_map')}</SectionTitle>
              <p className="text-xs text-gray-500 mb-3">{t('analysis.review.effective_map_subtitle')}</p>
              <EffectiveDistributionMap playerId={playerId} filters={filters} />
            </div>
          </div>
        </div>
      </ErrorBoundary>

      {/* STEP 2: 失点・得点前パターン */}
      <ErrorBoundary>
        <div>
          <p className="text-[10px] text-gray-500 font-semibold uppercase tracking-wider mb-2 pl-1">
            {t('analysis.review.section_patterns', 'STEP 2 — 失点・得点前パターン')}
          </p>
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
            <div className="bg-gray-800 rounded-lg p-4">
              <SectionTitle>{t('analysis.review.pre_loss_title')}</SectionTitle>
              <PreLossPatterns playerId={playerId} filters={filters} />
            </div>
            <div className="bg-gray-800 rounded-lg p-4">
              <SectionTitle>{t('analysis.review.pre_win_title')}</SectionTitle>
              <PreWinPatterns playerId={playerId} filters={filters} />
            </div>
          </div>
        </div>
      </ErrorBoundary>

      {/* STEP 3: スコア推移 */}
      <ErrorBoundary>
        <div>
          <p className="text-[10px] text-gray-500 font-semibold uppercase tracking-wider mb-2 pl-1">
            STEP 3 — スコア推移
          </p>
          <div className="bg-gray-800 rounded-lg p-4">
            <div className="flex items-center justify-between mb-3">
              <SectionTitle>{t('analysis.score_progression.title')}</SectionTitle>
              <SearchableSelect
                options={matchOptions}
                value={selectedMatchId}
                onChange={(v) => setSelectedMatchId(v != null ? Number(v) : null)}
                emptyLabel="— 試合を選択 —"
                placeholder="日付・対戦相手で検索..."
                className="max-w-[260px]"
              />
            </div>
            {selectedMatchId ? (
              <ScoreProgression matchId={selectedMatchId} onSetPointClick={handleSetPointClick} />
            ) : (
              <p className="text-gray-500 text-sm text-center py-4">試合を選択するとスコア推移が表示されます</p>
            )}
          </div>
        </div>
      </ErrorBoundary>

      {/* STEP 4: セット比較 */}
      <ErrorBoundary>
        <div>
          <p className="text-[10px] text-gray-500 font-semibold uppercase tracking-wider mb-2 pl-1">
            {t('analysis.review.section_sets', 'STEP 4 — セット別変化点')}
          </p>
          <div className="bg-gray-800 rounded-lg p-4">
            <SectionTitle>セット別パフォーマンス</SectionTitle>
            <SetComparison playerId={playerId} filters={filters} />
          </div>
        </div>
      </ErrorBoundary>

      {/* STEP 5: ラリーシーケンス */}
      <ErrorBoundary>
        <div>
          <p className="text-[10px] text-gray-500 font-semibold uppercase tracking-wider mb-2 pl-1">
            {t('analysis.review.section_sequence', 'STEP 5 — ラリーシーケンス深掘り')}
          </p>
          <RallySequencePatterns playerId={playerId} />
        </div>
      </ErrorBoundary>

      {/* SetIntervalSummary モーダル */}
      {pointAnalysis && (
        <ErrorBoundary>
          <SetIntervalSummary
            setId={pointAnalysis.setId}
            playerAName="選手"
            playerBName={matches.find((m) => m.match_id === selectedMatchId)?.opponent ?? 'B'}
            onClose={() => setPointAnalysis(null)}
            onNextSet={() => setPointAnalysis(null)}
            isMidGame={true}
            midGameScoreA={pointAnalysis.scoreA}
            midGameScoreB={pointAnalysis.scoreB}
            maxRallyNum={pointAnalysis.rallyNum}
            titleOverride={`Set ${pointAnalysis.setNum} 途中解析（ラリー ${pointAnalysis.rallyNum}）`}
            closeLabel="閉じる"
          />
        </ErrorBoundary>
      )}
    </div>
  )
}
