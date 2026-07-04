import { useEffect, useState } from 'react'
import { analyticsViewLifecycle } from '@/utils/analytics'
import { useTranslation } from 'react-i18next'
import { apiGet } from '@/api/client'
import { ErrorBoundary } from '@/components/common/ErrorBoundary'
import { AnalysisFilters } from '@/types'
import { FlashAdvicePanel } from '@/components/analysis/FlashAdvicePanel'
import { IntervalReport } from '@/components/analysis/IntervalReport'
import { SetIntervalSummary } from '@/components/analysis/SetIntervalSummary'
import { RallyPickerModal } from '@/components/analysis/RallyPickerModal'
import { RecommendationRanking } from '@/components/analysis/RecommendationRanking'
import { QuickSummaryCard } from '@/components/analysis/QuickSummaryCard'
import { SearchableSelect } from '@/components/common/SearchableSelect'
import { useCardTheme } from '@/hooks/useCardTheme'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { AnomalyBanner } from '@/components/dashboard/live/AnomalyBanner'
import { IntervalSuggestionsStrip } from '@/components/dashboard/live/IntervalSuggestionsStrip'
import { BenchModeToggle, useBenchMode } from '@/components/dashboard/live/BenchModeToggle'
import { useAuth } from '@/hooks/useAuth'

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
  useEffect(() => analyticsViewLifecycle('dashboard.live'), [])
  const { t } = useTranslation()
  const { card, textMuted } = useCardTheme()
  const isLight = useIsLightMode()
  const { role } = useAuth()
  const isCoachish = role === 'coach' || role === 'analyst' || role === 'admin'
  const [benchMode, setBenchMode] = useBenchMode()

  // 速報用ステート
  const [flashMatchId, setFlashMatchId] = useState<number | null>(null)
  const [flashSet, setFlashSet] = useState(1)
  const [flashRallyNum, setFlashRallyNum] = useState('')
  const [showRallyPicker, setShowRallyPicker] = useState(false)

  // インターバルレポート用ステート
  const [selectedMatchId, setSelectedMatchId] = useState<number | null>(null)
  // intervalSet=3 (= 全セット) を default。旧版は 1/2/3 を選ばせていたが、
  // 「セット間 = 試合進行に伴うセット推移」を見るのが目的なら全セット表示が
  // 正解 (ユーザ報告: 「選ばせる意味がない」)。
  const [intervalSet, _setIntervalSet] = useState(3)

  // セット間解析モーダル用ステート
  const [intervalSummarySetId, setIntervalSummarySetIdValue] = useState<number | null>(null)
  const [showIntervalSummary, setShowIntervalSummary] = useState(false)

  const matchOptions = matches.map((m) => ({
    value: m.match_id,
    label: `${m.date ?? t('common.unknown_date', 'Date unknown')} vs ${m.opponent}`,
    suffix: m.result === 'win' ? t('common.win_short', 'W') : t('common.lose_short', 'L'),
    searchText: `${m.date ?? ''} ${m.opponent} ${m.tournament} ${m.tournament_level}`,
  }))

  return (
    <div
      className={
        benchMode
          ? 'space-y-4 bg-gray-900 text-white p-3 rounded-ss-lg text-xl'
          : 'space-y-4'
      }
    >
      {/* ベンチモード toggle + ライブ強化バナー類 (coach 以上のみ) */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <BenchModeToggle active={benchMode} onToggle={setBenchMode} />
      </div>
      {isCoachish && flashMatchId && (
        <AnomalyBanner playerId={playerId} matchId={flashMatchId} windowSize={5} />
      )}
      {isCoachish && flashMatchId && !benchMode && (
        <IntervalSuggestionsStrip
          playerId={playerId}
          matchId={flashMatchId}
          setScore={0}
          rallyCountSinceLast={0}
        />
      )}
      {isCoachish && flashMatchId && benchMode && (
        <IntervalSuggestionsStrip
          playerId={playerId}
          matchId={flashMatchId}
          setScore={11}
          rallyCountSinceLast={0}
        />
      )}

      {/* 速報アドバイス */}
      <ErrorBoundary>
        <div className="space-y-4">
          {/* 試合 / セット / 地点 セレクター */}
          <div className={`${card} rounded-ss-lg shadow-card p-4`}>
            <SectionTitle>{t('analysis.flash.title')}</SectionTitle>
            <div className="flex flex-wrap gap-3 mt-3">
              <div className="flex flex-col gap-1 min-w-[180px] flex-1">
                <label className={`text-xs ${textMuted}`}>{t('auto.DashboardLivePage.k1')}</label>
                <SearchableSelect
                  options={matches.map((m) => {
                    const scoreStr = m.set_scores?.map(
                      (s) => `${s.score_player}-${s.score_opponent}${s.won ? '○' : '●'}`
                    ).join(' ') ?? ''
                    return {
                      value: m.match_id,
                      label: `${m.date} vs ${m.opponent}`,
                      suffix: scoreStr || (m.result === 'win' ? t('common.win_short', 'W') : t('common.lose_short', 'L')),
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
                  placeholder={t('auto.DashboardLivePage.k4')}
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
                      className={`px-3 py-1 text-xs rounded-ss-md font-medium transition-colors duration-fast ease-out ss-num ${flashSet === n ? 'bg-blue-600 text-white' : isLight ? 'bg-gray-100 text-gray-600 hover:bg-gray-200' : 'bg-gray-700 text-gray-400 hover:bg-gray-600'}`}
                    >
                      {t('auto.DashboardLivePage.set_n', { n })}
                    </button>
                  ))}
                </div>
              </div>

              <div className="flex flex-col gap-1">
                <label className={`text-xs ${textMuted}`}>{t('analysis.flash.rally_select')}</label>
                <button
                  disabled={!flashMatchId}
                  onClick={() => setShowRallyPicker(true)}
                  title={flashRallyNum ? `Set ${flashSet} — R.${flashRallyNum}` : undefined}
                  className={`px-3 py-1 text-xs rounded-ss-md font-medium transition-colors duration-fast ease-out disabled:opacity-40 disabled:cursor-not-allowed truncate max-w-full ss-num ${isLight ? 'bg-gray-100 text-gray-700 hover:bg-gray-200 border border-gray-300' : 'bg-gray-700 text-gray-300 hover:bg-gray-600 border border-gray-600'}`}
                >
                  {flashRallyNum ? `Set ${flashSet} — R.${flashRallyNum}` : t('live.all_rallies_pick_from_chart', 'All rallies (pick from chart)')}
                </button>
              </div>
            </div>
          </div>

          {/* コーチ向け一言カード（試合選択後に表示）。
              製品ルール: player ロールには弱点表現・コーチ向け指示を見せない。
              バックエンド /api/review/quick_summary も player を 403 でゲート済み。 */}
          {flashMatchId && isCoachish && (
            <QuickSummaryCard
              matchId={flashMatchId}
              asOfSet={flashSet}
              asOfRally={flashRallyNum ? Number(flashRallyNum) : undefined}
            />
          )}

          {flashMatchId ? (
            <div className={`${card} rounded-ss-lg shadow-card p-4`}>
              <FlashAdvicePanel
                matchId={flashMatchId}
                asOfSet={flashSet}
                asOfRallyNum={flashRallyNum ? Number(flashRallyNum) : undefined}
                playerId={playerId}
              />
            </div>
          ) : (
            <div className={`${card} rounded-ss-lg shadow-flat p-6 text-center text-sm ${isLight ? 'text-gray-400' : 'text-gray-500'}`}>
              {t('live.pick_to_see_advice', 'Pick a match and player to see live advice')}
            </div>
          )}

          {/* 推奨アドバイスランキング (ベンチモード時は非表示で集中度UP) */}
          {!benchMode && <RecommendationRanking playerId={playerId} />}

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

      {/* インターバルレポート (ベンチモード時は非表示) */}
      {!benchMode && (
      <ErrorBoundary>
        <div className={`${card} rounded-ss-lg shadow-card p-4`}>
          <div className="flex items-center justify-between mb-3">
            <SectionTitle>{t('analysis.interval_report.title')}</SectionTitle>
            <div className="flex gap-2 items-center flex-wrap">
              <SearchableSelect
                options={matchOptions}
                value={selectedMatchId}
                onChange={(v) => setSelectedMatchId(v != null ? Number(v) : null)}
                emptyLabel={t('common.select_match', 'Select match')}
                placeholder={t('auto.DashboardLivePage.k4')}
                className="max-w-[260px]"
              />
              {/* セット選択 input は廃止 (default で全 3 セット表示する仕様)。
                 完了セットだけを部分表示したいケースは通常無いため。 */}
            </div>
          </div>
          {selectedMatchId ? (
            <IntervalReport
              matchId={selectedMatchId}
              completedSet={intervalSet}
              onSetClick={async (setNum) => {
                if (!selectedMatchId) return
                try {
                  // match の sets 一覧から set_num に対応する set_id を解決
                  const resp = await apiGet<{ success: boolean; data: Array<{ id: number; set_num: number }> }>(
                    `/sets/match/${selectedMatchId}`,
                  )
                  const found = resp.data?.find((s) => s.set_num === setNum)
                  if (found) {
                    setIntervalSummarySetIdValue(found.id)
                    setShowIntervalSummary(true)
                  }
                } catch {
                  /* 失敗時は静かに無視 (ユーザに虚偽情報を出さない) */
                }
              }}
            />
          ) : (
            <p className={`text-sm text-center py-6 ${isLight ? 'text-gray-400' : 'text-gray-500'}`}>{t('auto.DashboardLivePage.k3')}</p>
          )}
        </div>
      </ErrorBoundary>
      )}

      {/* SetIntervalSummary モーダル */}
      {showIntervalSummary && intervalSummarySetId && (
        <ErrorBoundary>
          <SetIntervalSummary
            setId={intervalSummarySetId}
            playerAName={t('common.player', 'Player')}
            playerBName={matches.find((m) => m.match_id === selectedMatchId)?.opponent ?? 'B'}
            onClose={() => setShowIntervalSummary(false)}
            onNextSet={() => setShowIntervalSummary(false)}
            isMidGame={false}
          />
        </ErrorBoundary>
      )}
    </div>
  )
}
