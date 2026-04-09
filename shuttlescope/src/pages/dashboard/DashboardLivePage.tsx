import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ErrorBoundary } from '@/components/common/ErrorBoundary'
import { AnalysisFilters } from '@/types'
import { FlashAdvicePanel } from '@/components/analysis/FlashAdvicePanel'
import { IntervalReport } from '@/components/analysis/IntervalReport'
import { SetIntervalSummary } from '@/components/analysis/SetIntervalSummary'
import { RallyPickerModal } from '@/components/analysis/RallyPickerModal'
import { RecommendationRanking } from '@/components/analysis/RecommendationRanking'
import { SearchableSelect } from '@/components/common/SearchableSelect'
import { useCardTheme } from '@/hooks/useCardTheme'
import { useIsLightMode } from '@/hooks/useIsLightMode'

interface SetScore {
  set_num: number
  score_player: number
  score_opponent: number
  won: boolean
}

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
  set_scores: SetScore[]
}

interface Props {
  playerId: number
  filters: AnalysisFilters
  matches: MatchSummary[]
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  const isLight = useIsLightMode()
  return <h2 className={`text-sm font-semibold mb-0 ${isLight ? 'text-gray-700' : 'text-gray-300'}`}>{children}</h2>
}

export function DashboardLivePage({ playerId, matches }: Props) {
  const { t } = useTranslation()
  const { card, textMuted } = useCardTheme()
  const isLight = useIsLightMode()

  // 速報用ステート
  const [flashMatchId, setFlashMatchId] = useState<number | null>(null)
  const [flashSet, setFlashSet] = useState(1)
  const [flashRallyNum, setFlashRallyNum] = useState('')
  const [showRallyPicker, setShowRallyPicker] = useState(false)

  // インターバルレポート用ステート
  const [selectedMatchId, setSelectedMatchId] = useState<number | null>(null)
  const [intervalSet, setIntervalSet] = useState(1)

  // セット間解析モーダル用ステート
  const [intervalSummaryMatchId, setIntervalSummaryMatchId] = useState<number | null>(null)
  const [showIntervalSummary, setShowIntervalSummary] = useState(false)

  const matchOptions = matches.map((m) => ({
    value: m.match_id,
    label: `${m.date ?? '日付不明'} vs ${m.opponent}`,
    suffix: m.result === 'win' ? '勝' : '負',
    searchText: `${m.date ?? ''} ${m.opponent} ${m.tournament} ${m.tournament_level}`,
  }))

  return (
    <div className="space-y-4">
      {/* 速報アドバイス */}
      <ErrorBoundary>
        <div className="space-y-4">
          {/* 試合 / セット / 地点 セレクター */}
          <div className={`${card} rounded-lg p-4`}>
            <SectionTitle>{t('analysis.flash.title')}</SectionTitle>
            <div className="flex flex-wrap gap-3 mt-3">
              <div className="flex flex-col gap-1 min-w-[180px] flex-1">
                <label className={`text-xs ${textMuted}`}>試合</label>
                <SearchableSelect
                  options={matches.map((m) => {
                    const scoreStr = m.set_scores?.map(
                      (s) => `${s.score_player}-${s.score_opponent}${s.won ? '○' : '●'}`
                    ).join(' ') ?? ''
                    return {
                      value: m.match_id,
                      label: `${m.date} vs ${m.opponent}`,
                      suffix: scoreStr || (m.result === 'win' ? '勝' : '負'),
                      searchText: `${m.date} ${m.opponent} ${m.tournament}`,
                    }
                  })}
                  value={flashMatchId}
                  onChange={(v) => {
                    setFlashMatchId(v != null ? Number(v) : null)
                    setFlashSet(1)
                    setFlashRallyNum('')
                  }}
                  emptyLabel={t('analysis.flash.no_match')}
                  placeholder="日付・対戦相手で検索..."
                />
              </div>

              <div className="flex flex-col gap-1">
                <label className={`text-xs ${textMuted}`}>{t('analysis.flash.set_select')}</label>
                <div className="flex gap-1">
                  {Array.from(
                    { length: matches.find((m) => m.match_id === flashMatchId)?.set_count || 3 },
                    (_, i) => i + 1
                  ).map((n) => (
                    <button
                      key={n}
                      onClick={() => setFlashSet(n)}
                      className={`px-3 py-1 text-xs rounded font-medium transition-colors ${flashSet === n ? 'bg-blue-600 text-white' : isLight ? 'bg-gray-100 text-gray-600 hover:bg-gray-200' : 'bg-gray-700 text-gray-400 hover:bg-gray-600'}`}
                    >
                      Set {n}
                    </button>
                  ))}
                </div>
              </div>

              <div className="flex flex-col gap-1">
                <label className={`text-xs ${textMuted}`}>{t('analysis.flash.rally_select')}</label>
                <button
                  disabled={!flashMatchId}
                  onClick={() => setShowRallyPicker(true)}
                  className={`px-3 py-1 text-xs rounded font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap ${isLight ? 'bg-gray-100 text-gray-700 hover:bg-gray-200 border border-gray-300' : 'bg-gray-700 text-gray-300 hover:bg-gray-600 border border-gray-600'}`}
                >
                  {flashRallyNum ? `Set ${flashSet} — R.${flashRallyNum}` : '全ラリー（グラフから選択）'}
                </button>
              </div>
            </div>
          </div>

          {flashMatchId ? (
            <div className={`${card} rounded-lg p-4`}>
              <FlashAdvicePanel
                matchId={flashMatchId}
                asOfSet={flashSet}
                asOfRallyNum={flashRallyNum ? Number(flashRallyNum) : undefined}
                playerId={playerId}
              />
            </div>
          ) : (
            <div className={`${card} rounded-lg p-6 text-center text-sm ${isLight ? 'text-gray-400' : 'text-gray-500'}`}>
              試合と選手を選択すると速報アドバイスが表示されます
            </div>
          )}

          {/* 推奨アドバイスランキング */}
          <RecommendationRanking playerId={playerId} />

          {showRallyPicker && flashMatchId && (
            <RallyPickerModal
              matchId={flashMatchId}
              matchLabel={(() => {
                const m = matches.find((m) => m.match_id === flashMatchId)
                return m ? `${m.date} vs ${m.opponent}` : ''
              })()}
              initialSet={flashSet}
              selectedRallyNum={flashRallyNum ? Number(flashRallyNum) : null}
              onSelect={(setNum, rallyNum) => {
                setFlashSet(setNum)
                setFlashRallyNum(String(rallyNum))
              }}
              onClear={() => setFlashRallyNum('')}
              onClose={() => setShowRallyPicker(false)}
            />
          )}
        </div>
      </ErrorBoundary>

      {/* インターバルレポート */}
      <ErrorBoundary>
        <div className={`${card} rounded-lg p-4`}>
          <div className="flex items-center justify-between mb-3">
            <SectionTitle>{t('analysis.interval_report.title')}</SectionTitle>
            <div className="flex gap-2 items-center flex-wrap">
              <SearchableSelect
                options={matchOptions}
                value={selectedMatchId}
                onChange={(v) => setSelectedMatchId(v != null ? Number(v) : null)}
                emptyLabel="— 試合を選択 —"
                placeholder="日付・対戦相手で検索..."
                className="max-w-[260px]"
              />
              {selectedMatchId && (
                <>
                  <label className={`text-xs ${textMuted}`}>完了セット:</label>
                  <input
                    type="number"
                    min={1}
                    max={3}
                    value={intervalSet}
                    onChange={(e) => setIntervalSet(Number(e.target.value))}
                    className={`w-12 text-xs rounded px-2 py-1 ${isLight ? 'bg-white border border-gray-300 text-gray-900' : 'bg-gray-700 border border-gray-600 text-white'}`}
                  />
                </>
              )}
            </div>
          </div>
          {selectedMatchId ? (
            <IntervalReport matchId={selectedMatchId} completedSet={intervalSet} />
          ) : (
            <p className={`text-sm text-center py-6 ${isLight ? 'text-gray-400' : 'text-gray-500'}`}>試合を選択するとインターバルレポートが表示されます</p>
          )}
        </div>
      </ErrorBoundary>

      {/* SetIntervalSummary モーダル */}
      {showIntervalSummary && intervalSummaryMatchId && (
        <ErrorBoundary>
          <SetIntervalSummary
            setId={intervalSummaryMatchId}
            playerAName="選手"
            playerBName={matches.find((m) => m.match_id === intervalSummaryMatchId)?.opponent ?? 'B'}
            onClose={() => setShowIntervalSummary(false)}
            onNextSet={() => setShowIntervalSummary(false)}
            isMidGame={false}
          />
        </ErrorBoundary>
      )}
    </div>
  )
}
