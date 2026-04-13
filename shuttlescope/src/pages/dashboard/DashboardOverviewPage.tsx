import { useState, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
} from 'recharts'
import { CourtDiagram } from '@/components/court/CourtDiagram'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { RoleGuard } from '@/components/common/RoleGuard'
import { ErrorBoundary } from '@/components/common/ErrorBoundary'
import { apiGet } from '@/api/client'
import { AnalysisFilters } from '@/types'
import { Maximize2, ChevronLeft, ChevronRight } from 'lucide-react'
import { BAR, TOOLTIP_STYLE as CW_TOOLTIP, getTooltipStyle, AXIS_TICK_LIGHT } from '@/styles/colors'
import { useCardTheme } from '@/hooks/useCardTheme'
import { ScoreProgression, type RallyPoint } from '@/components/analysis/ScoreProgression'
import { IntervalReport } from '@/components/analysis/IntervalReport'
import { ConfidenceCalibration } from '@/components/analysis/ConfidenceCalibration'
import { ChartModal } from '@/components/common/ChartModal'
import { CourtHeatModal } from '@/components/analysis/CourtHeatModal'
import { SetIntervalSummary } from '@/components/analysis/SetIntervalSummary'
import { SearchableSelect } from '@/components/common/SearchableSelect'

interface DescriptiveData {
  total_matches: number
  total_rallies: number
  win_rate: number
  avg_rally_length: number
  end_type_distribution: Record<string, number>
  rally_length_histogram: { length: number; count: number }[]
  win_by_end_type: Record<string, { wins: number; total: number }>
  server_win_rate: { as_server: number; as_receiver: number }
}

interface HeatmapResponse {
  success: boolean
  data: Record<string, number>
  meta?: { sample_size?: number }
}

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

const END_TYPE_LABELS: Record<string, string> = {
  ace: 'エース',
  forced_error: '強制エラー',
  unforced_error: '非強制エラー',
  net_error: 'ネットエラー',
  net: 'ネットエラー',
  out: 'アウト',
  winner: 'ウィナー',
  cant_reach: '届かず',
}

function pct(value: number) {
  return `${(value * 100).toFixed(1)}%`
}

type SortCol = 'date' | 'opponent' | 'tournament_level' | 'result' | 'rally_count'

interface Props {
  playerId: number
  filters: AnalysisFilters
  filterApiParams: Record<string, string>
  matches: MatchSummary[]
  loadingMatches: boolean
}

export function DashboardOverviewPage({ playerId, filters, filterApiParams, matches, loadingMatches }: Props) {
  const { t } = useTranslation()
  const { card, textHeading, textSecondary, textMuted, textFaint, loading: loadingClass, isLight } = useCardTheme()

  const TOOLTIP_STYLE = getTooltipStyle(isLight)
  const AXIS_TICK = isLight ? AXIS_TICK_LIGHT : '#9ca3af'

  const SectionTitle = ({ children }: { children: React.ReactNode }) => (
    <h2 className={`text-sm font-semibold ${textHeading} mb-0`}>{children}</h2>
  )
  const ExpandBtn = ({ onClick }: { onClick: () => void }) => (
    <button
      onClick={onClick}
      title="全画面で表示"
      className={`shrink-0 ${textMuted} hover:${textHeading} transition-colors p-1 rounded ${isLight ? 'hover:bg-gray-100' : 'hover:bg-gray-700'}`}
    >
      <Maximize2 size={13} />
    </button>
  )
  const LoadingRow = () => (
    <div className={`${loadingClass} text-sm py-4 text-center`}>読み込み中...</div>
  )

  // ローカル状態
  const [heatmapTab, setHeatmapTab] = useState<'hit' | 'land'>('hit')
  const [heatmapMatchId, setHeatmapMatchId] = useState<number | null>(null)
  const [heatmapLastN, setHeatmapLastN] = useState<number | null>(null)
  const [selectedMatchId, setSelectedMatchId] = useState<number | null>(null)
  const [intervalSet, setIntervalSet] = useState(1)
  const [expandedChart, setExpandedChart] = useState<string | null>(null)
  const [courtHeatOpen, setCourtHeatOpen] = useState(false)
  const [matchSort, setMatchSort] = useState<{ col: SortCol; order: 'asc' | 'desc' }>({ col: 'date', order: 'desc' })
  const [pointAnalysis, setPointAnalysis] = useState<{
    setId: number; setNum: number; rallyNum: number; scoreA: number; scoreB: number
    rally: RallyPoint & { set_num: number }
    setRallies: RallyPoint[]
  } | null>(null)

  // ── Descriptive ──
  const { data: descriptiveResp, isLoading: loadingDescriptive } = useQuery({
    queryKey: ['analysis-descriptive', playerId, filters],
    queryFn: () =>
      apiGet<{ success: boolean; data: DescriptiveData; meta?: { sample_size?: number } }>(
        '/analysis/descriptive',
        { player_id: playerId, ...filterApiParams }
      ),
  })
  const descriptive: DescriptiveData | null = descriptiveResp?.data ?? null

  // ── Heatmap専用フィルターパラメータ ──
  const heatmapApiParams = (() => {
    if (heatmapMatchId != null) return { match_id: heatmapMatchId }
    if (heatmapLastN != null) {
      const recent = [...matches]
        .sort((a, b) => (b.date ?? '').localeCompare(a.date ?? ''))
        .slice(0, heatmapLastN)
      const ids = recent.map((m) => m.match_id).join(',')
      return ids ? { match_ids: ids } : {}
    }
    return {}
  })()

  const { data: heatmapHitResp, isLoading: loadingHeatmapHit } = useQuery({
    queryKey: ['analysis-heatmap-hit', playerId, heatmapMatchId, heatmapLastN],
    queryFn: () =>
      apiGet<HeatmapResponse>('/analysis/heatmap', { player_id: playerId, type: 'hit', ...heatmapApiParams }),
  })

  const { data: heatmapLandResp, isLoading: loadingHeatmapLand } = useQuery({
    queryKey: ['analysis-heatmap-land', playerId, heatmapMatchId, heatmapLastN],
    queryFn: () =>
      apiGet<HeatmapResponse>('/analysis/heatmap', { player_id: playerId, type: 'land', ...heatmapApiParams }),
  })

  const heatmapHit: Record<string, number> = heatmapHitResp?.data ?? {}
  const heatmapLand: Record<string, number> = heatmapLandResp?.data ?? {}

  // 試合テーブルのソート
  function toggleSort(col: SortCol) {
    setMatchSort((prev) =>
      prev.col === col
        ? { col, order: prev.order === 'asc' ? 'desc' : 'asc' }
        : { col, order: col === 'date' || col === 'rally_count' ? 'desc' : 'asc' }
    )
  }

  const filteredMatches = [...matches]
    .filter((m) => {
      if (filters.result !== 'all' && m.result !== filters.result) return false
      if (filters.tournamentLevel && m.tournament_level !== filters.tournamentLevel) return false
      if (filters.dateFrom && (m.date ?? '') < filters.dateFrom) return false
      if (filters.dateTo && (m.date ?? '') > filters.dateTo) return false
      return true
    })
    .sort((a, b) => {
      const dir = matchSort.order === 'asc' ? 1 : -1
      switch (matchSort.col) {
        case 'date':             return dir * (a.date ?? '').localeCompare(b.date ?? '')
        case 'opponent':         return dir * a.opponent.localeCompare(b.opponent, 'ja')
        case 'tournament_level': return dir * (a.tournament_level ?? '').localeCompare(b.tournament_level ?? '')
        case 'result':           return dir * (a.result ?? '').localeCompare(b.result ?? '')
        case 'rally_count':      return dir * (a.rally_count - b.rally_count)
        default:                 return 0
      }
    })

  const endTypeData = descriptive
    ? Object.entries(descriptive.end_type_distribution).map(([key, count]) => ({
        name: END_TYPE_LABELS[key] ?? key,
        count,
      }))
    : []

  const matchOptions = matches.map((m) => ({
    value: m.match_id,
    label: `${m.date ?? '日付不明'} vs ${m.opponent}`,
    suffix: [m.tournament_level, m.result === 'win' ? '勝' : '負'].filter(Boolean).join(' '),
    searchText: `${m.date ?? ''} ${m.opponent} ${m.tournament} ${m.tournament_level}`,
  }))

  const matchNavIdx = matchOptions.findIndex((o) => o.value === selectedMatchId)
  const canGoPrev = matchNavIdx > 0
  const canGoNext = matchNavIdx >= 0 && matchNavIdx < matchOptions.length - 1

  const handleSetPointClick = useCallback((
    setId: number, setNum: number, rallyNum: number, scoreA: number, scoreB: number, rally: RallyPoint, setRallies: RallyPoint[]
  ) => {
    setPointAnalysis({ setId, setNum, rallyNum, scoreA, scoreB, rally: { ...rally, set_num: setNum }, setRallies })
  }, [])

  return (
    <div className="space-y-5">
      {/* 2カラムレイアウト */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
        {/* 左カラム */}
        <div className="xl:col-span-2 space-y-5 min-w-0">
          {/* ラリー終了タイプ */}
          <div className={`${card} rounded-lg p-4`}>
            <div className="flex items-center justify-between mb-3">
              <SectionTitle>ラリー終了タイプ</SectionTitle>
              <div className="flex items-center gap-2">
                {descriptive && (
                  <ConfidenceBadge sampleSize={descriptive.total_rallies} className="text-[10px] shrink-0" />
                )}
                <ExpandBtn onClick={() => setExpandedChart('end_type')} />
              </div>
            </div>
            {loadingDescriptive ? <LoadingRow /> : endTypeData.length === 0 ? (
              <p className={`${textMuted} text-sm text-center py-4`}>データなし</p>
            ) : (
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={endTypeData} layout="vertical" margin={{ top: 0, right: 16, left: 8, bottom: 0 }}>
                  <XAxis type="number" tick={{ fill: AXIS_TICK, fontSize: 11 }} />
                  <YAxis type="category" dataKey="name" width={80} tick={{ fill: AXIS_TICK, fontSize: 11 }} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: isLight ? 'rgba(0,0,0,0.04)' : 'rgba(255,255,255,0.05)' }} />
                  <Bar dataKey="count" fill={BAR} radius={[0, 3, 3, 0]} name="件数" />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>

          {/* ラリー長分布 */}
          <div className={`${card} rounded-lg p-4`}>
            <div className="flex items-center justify-between mb-3">
              <SectionTitle>ラリー長分布（〜20打）</SectionTitle>
              <div className="flex items-center gap-2">
                {descriptive && (
                  <ConfidenceBadge sampleSize={descriptive.total_rallies} className="text-[10px] shrink-0" />
                )}
                <ExpandBtn onClick={() => setExpandedChart('rally_dist')} />
              </div>
            </div>
            {loadingDescriptive ? <LoadingRow /> : !descriptive ? (
              <p className={`${textMuted} text-sm text-center py-4`}>データなし</p>
            ) : (
              <ResponsiveContainer width="100%" height={200}>
                <BarChart
                  data={descriptive.rally_length_histogram.filter((d) => d.length <= 20).map((d) => ({ name: String(d.length), count: d.count }))}
                  margin={{ top: 0, right: 8, left: 0, bottom: 0 }}
                >
                  <XAxis dataKey="name" tick={{ fill: AXIS_TICK, fontSize: 11 }} label={{ value: '打数', position: 'insideBottomRight', offset: -4, fill: AXIS_TICK, fontSize: 10 }} />
                  <YAxis tick={{ fill: AXIS_TICK, fontSize: 11 }} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: isLight ? 'rgba(0,0,0,0.04)' : 'rgba(255,255,255,0.05)' }} />
                  <Bar dataKey="count" fill={BAR} radius={[3, 3, 0, 0]} name="件数" />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

        {/* 右カラム */}
        <div className="space-y-5 min-w-0">
          {/* コートヒートマップ */}
          <div className={`${card} rounded-lg p-4`}>
            <div className="flex flex-wrap items-center gap-2 mb-3">
              <SectionTitle>コートヒートマップ</SectionTitle>
              <div className="flex items-center gap-1 ml-auto shrink-0">
                {(() => {
                  const s = heatmapTab === 'hit' ? heatmapHitResp?.meta?.sample_size : heatmapLandResp?.meta?.sample_size
                  return s != null && s > 0 ? <ConfidenceBadge sampleSize={s} className="text-[10px]" /> : null
                })()}
                <ExpandBtn onClick={() => setCourtHeatOpen(true)} />
              </div>
            </div>
            <div className="flex gap-1 mb-2">
              {(['hit', 'land'] as const).map((tab) => (
                <button
                  key={tab}
                  onClick={() => setHeatmapTab(tab)}
                  className={`flex-1 text-xs py-1.5 rounded font-medium transition-colors ${heatmapTab === tab ? (isLight ? 'bg-gray-400 text-white' : 'bg-gray-600 text-white') : (isLight ? 'bg-gray-100 text-gray-500 hover:bg-gray-200' : 'bg-gray-700 text-gray-400 hover:bg-gray-600')}`}
                >
                  {tab === 'hit' ? '打点' : '着地点'}
                </button>
              ))}
            </div>
            <div className="mb-3 space-y-1.5">
              <div className="flex gap-1 flex-wrap">
                {([null, 3, 5, 10] as const).map((n) => (
                  <button
                    key={n ?? 'all'}
                    onClick={() => { setHeatmapLastN(n); setHeatmapMatchId(null) }}
                    disabled={heatmapMatchId != null}
                    className={`text-[11px] px-2 py-0.5 rounded border transition-colors ${heatmapMatchId == null && heatmapLastN === n ? (isLight ? 'bg-gray-400 border-gray-300 text-white' : 'bg-gray-500 border-gray-400 text-white') : (isLight ? 'bg-white border-gray-300 text-gray-500 hover:bg-gray-100 disabled:opacity-40' : 'bg-gray-700 border-gray-600 text-gray-400 hover:bg-gray-600 disabled:opacity-40')}`}
                  >
                    {n == null ? '全期間' : `直近${n}試合`}
                  </button>
                ))}
              </div>
              {matches.length > 0 && (
                <select
                  value={heatmapMatchId ?? ''}
                  onChange={(e) => {
                    const v = e.target.value
                    setHeatmapMatchId(v ? Number(v) : null)
                    if (v) setHeatmapLastN(null)
                  }}
                  className={`w-full text-[11px] rounded px-2 py-1 focus:outline-none ${isLight ? 'bg-white border border-gray-300 text-gray-700' : 'bg-gray-700 border border-gray-600 text-gray-300'}`}
                >
                  <option value="">試合を選択（個別）</option>
                  {[...matches].sort((a, b) => (b.date ?? '').localeCompare(a.date ?? '')).map((m) => (
                    <option key={m.match_id} value={m.match_id}>
                      {m.date ?? '日付不明'} {m.opponent} ({m.result === 'win' ? '勝' : '敗'})
                    </option>
                  ))}
                </select>
              )}
            </div>
            {(heatmapTab === 'hit' ? loadingHeatmapHit : loadingHeatmapLand) ? <LoadingRow /> : (
              <div className="flex flex-col items-center">
                <CourtDiagram
                  mode={heatmapTab}
                  heatmapData={heatmapTab === 'hit' ? heatmapHit : heatmapLand}
                  interactive={true}
                  selectedZone={null}
                  onZoneSelect={() => setCourtHeatOpen(true)}
                  label={heatmapTab === 'hit' ? '打点分布' : '着地点分布'}
                />
                <p className={`text-[10px] ${textFaint} mt-1`}>クリックで詳細分析を開く</p>
              </div>
            )}
          </div>

          {/* サーブ勝率 */}
          <RoleGuard
            allowedRoles={['analyst', 'coach']}
            fallback={
              <div className={`${card} rounded-lg p-4`}>
                <p className={`text-xs ${textMuted} text-center py-2`}>※ このコンテンツはアナリスト・コーチ向けです</p>
              </div>
            }
          >
            <div className={`${card} rounded-lg p-4`}>
              <div className="flex items-center justify-between mb-3">
                <SectionTitle>サーブ勝率</SectionTitle>
                {descriptive && <ConfidenceBadge sampleSize={descriptive.total_rallies} className="text-[10px] shrink-0" />}
              </div>
              {loadingDescriptive || !descriptive?.server_win_rate ? <LoadingRow /> : (
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <span className={`text-sm ${textSecondary}`}>サーバー時</span>
                    <span className="text-lg font-semibold text-blue-400">{pct(descriptive.server_win_rate.as_server)}</span>
                  </div>
                  <div className={`w-full ${isLight ? 'bg-gray-200' : 'bg-gray-700'} rounded-full h-2`}>
                    <div className="bg-blue-500 h-2 rounded-full" style={{ width: `${(descriptive.server_win_rate.as_server * 100).toFixed(1)}%` }} />
                  </div>
                  <div className="flex items-center justify-between">
                    <span className={`text-sm ${textSecondary}`}>レシーバー時</span>
                    <span className="text-lg font-semibold text-emerald-400">{pct(descriptive.server_win_rate.as_receiver)}</span>
                  </div>
                  <div className={`w-full ${isLight ? 'bg-gray-200' : 'bg-gray-700'} rounded-full h-2`}>
                    <div className="bg-emerald-500 h-2 rounded-full" style={{ width: `${(descriptive.server_win_rate.as_receiver * 100).toFixed(1)}%` }} />
                  </div>
                </div>
              )}
            </div>
          </RoleGuard>
        </div>
      </div>

      {/* データ品質概況 */}
      <ConfidenceCalibration playerId={playerId} />

      {/* 試合一覧テーブル */}
      <div className={`${card} rounded-lg p-4`}>
        <div className="flex items-center justify-between mb-3">
          <SectionTitle>試合一覧</SectionTitle>
          <span className={`text-xs ${textMuted}`}>{filteredMatches.length} / {matches.length} 試合</span>
        </div>
        {loadingMatches ? <LoadingRow /> : filteredMatches.length === 0 ? (
          <p className={`${textMuted} text-sm text-center py-4`}>
            {matches.length > 0 ? 'フィルター条件に一致する試合がありません' : 'データなし'}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className={`${textSecondary} border-b ${isLight ? 'border-gray-200' : 'border-gray-700'}`}>
                  {([
                    { col: 'opponent' as const,        label: '対戦相手', align: 'left'   },
                    { col: null,                        label: '大会',     align: 'left'   },
                    { col: 'tournament_level' as const, label: 'レベル',   align: 'center' },
                    { col: 'date' as const,             label: '日付',     align: 'left'   },
                    { col: 'result' as const,           label: '結果',     align: 'center' },
                    { col: 'rally_count' as const,      label: 'ラリー',   align: 'right'  },
                  ] as const).map(({ col, label, align }) => (
                    <th
                      key={label}
                      className={`py-2 pr-3 font-medium select-none ${col ? `cursor-pointer ${isLight ? 'hover:text-gray-900' : 'hover:text-gray-200'}` : ''} text-${align}`}
                      onClick={() => col && toggleSort(col)}
                    >
                      {label}
                      {col && matchSort.col === col && (
                        <span className="ml-0.5 text-[10px]">{matchSort.order === 'asc' ? '▲' : '▼'}</span>
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredMatches.map((m) => (
                  <tr
                    key={m.match_id}
                    className={`border-b ${isLight ? 'border-gray-100 hover:bg-gray-50' : 'border-gray-700/50 hover:bg-gray-700/30'} transition-colors cursor-pointer`}
                    onClick={() => setSelectedMatchId(m.match_id)}
                  >
                    <td className={`py-2 pr-3 ${textHeading}`}>{m.opponent}</td>
                    <td className={`py-2 pr-3 ${textSecondary} text-xs`}>{m.tournament}</td>
                    <td className="py-2 pr-3 text-center"><span className={`text-xs ${textMuted}`}>{m.tournament_level ?? '—'}</span></td>
                    <td className={`py-2 pr-3 ${textSecondary} whitespace-nowrap`}>{m.date}</td>
                    <td className="py-2 pr-3 text-center">
                      <span className={`inline-block px-2 py-0.5 rounded text-xs font-semibold ${m.result === 'win' ? 'bg-blue-900 text-blue-300' : 'bg-red-900 text-red-300'}`}>
                        {m.result === 'win' ? '勝' : '負'}
                      </span>
                    </td>
                    <td className={`py-2 text-right ${textSecondary}`}>{m.rally_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* スコア推移 / インターバルレポート 共通試合選択 */}
      <div className={`${card} rounded-lg p-4`}>
        {/* 試合セレクタ（前後ナビ付き） */}
        <div className="flex items-center justify-between gap-2 mb-1">
          <SectionTitle>{t('analysis.score_progression.title')}</SectionTitle>
          <div className="flex items-center gap-1 shrink-0">
            <button
              onClick={() => setSelectedMatchId(matchOptions[matchNavIdx - 1].value as number)}
              disabled={!canGoPrev}
              title="前の試合"
              className={`p-1 rounded transition-colors disabled:opacity-30 ${isLight ? 'hover:bg-gray-100' : 'hover:bg-gray-700'}`}
            >
              <ChevronLeft size={14} className={textMuted} />
            </button>
            <SearchableSelect
              options={matchOptions}
              value={selectedMatchId}
              onChange={(v) => setSelectedMatchId(v != null ? Number(v) : null)}
              emptyLabel="— 試合を選択 —"
              placeholder="日付・対戦相手で検索..."
              dropdownAlign="right"
              className="w-[210px]"
            />
            <button
              onClick={() => setSelectedMatchId(matchOptions[matchNavIdx + 1].value as number)}
              disabled={!canGoNext}
              title="次の試合"
              className={`p-1 rounded transition-colors disabled:opacity-30 ${isLight ? 'hover:bg-gray-100' : 'hover:bg-gray-700'}`}
            >
              <ChevronRight size={14} className={textMuted} />
            </button>
          </div>
        </div>
        {/* 選択中の試合：大会名を補足表示 */}
        {selectedMatchId && (() => {
          const m = matches.find((mx) => mx.match_id === selectedMatchId)
          const sub = [m?.tournament, m?.tournament_level].filter(Boolean).join(' · ')
          return sub ? <p className={`text-xs ${textMuted} mb-3 truncate`}>{sub}</p> : <div className="mb-3" />
        })()}
        {selectedMatchId ? (
          <ScoreProgression matchId={selectedMatchId} onSetPointClick={handleSetPointClick} />
        ) : (
          <p className={`${textMuted} text-sm text-center py-6`}>試合を選択するとスコア推移が表示されます</p>
        )}
      </div>

      {/* インターバルレポート */}
      <div className={`${card} rounded-lg p-4`}>
        <div className="flex items-center justify-between gap-2 mb-3">
          <SectionTitle>{t('analysis.interval_report.title')}</SectionTitle>
          {selectedMatchId && (
            <div className="flex gap-1 shrink-0">
              {[1, 2, 3].map((n) => (
                <button
                  key={n}
                  onClick={() => setIntervalSet(n)}
                  className={`px-3 py-1 text-xs rounded font-medium transition-colors ${
                    intervalSet === n
                      ? 'bg-blue-600 text-white'
                      : isLight ? 'bg-gray-100 text-gray-500 hover:bg-gray-200' : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
                  }`}
                >
                  Set {n}
                </button>
              ))}
            </div>
          )}
        </div>
        {selectedMatchId ? (
          <IntervalReport matchId={selectedMatchId} completedSet={intervalSet} />
        ) : (
          <p className={`${textMuted} text-sm text-center py-6`}>試合を選択するとインターバルレポートが表示されます</p>
        )}
      </div>

      {/* 全画面グラフモーダル */}
      {expandedChart && (() => {
        const titles: Record<string, string> = {
          end_type: 'ラリー終了タイプ',
          rally_dist: 'ラリー長分布',
        }
        const renderContent = () => {
          if (expandedChart === 'end_type' && endTypeData.length > 0) {
            return (
              <ResponsiveContainer width="100%" height={500}>
                <BarChart data={endTypeData} layout="vertical" margin={{ top: 0, right: 24, left: 16, bottom: 0 }}>
                  <XAxis type="number" tick={{ fill: AXIS_TICK, fontSize: 13 }} />
                  <YAxis type="category" dataKey="name" width={100} tick={{ fill: AXIS_TICK, fontSize: 13 }} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} />
                  <Bar dataKey="count" fill={BAR} radius={[0, 4, 4, 0]} name="件数" />
                </BarChart>
              </ResponsiveContainer>
            )
          }
          if (expandedChart === 'rally_dist' && descriptive) {
            const data = descriptive.rally_length_histogram.filter((d) => d.length <= 20).map((d) => ({ name: String(d.length), count: d.count }))
            return (
              <ResponsiveContainer width="100%" height={400}>
                <BarChart data={data} margin={{ top: 0, right: 24, left: 0, bottom: 0 }}>
                  <XAxis dataKey="name" tick={{ fill: AXIS_TICK, fontSize: 13 }} />
                  <YAxis tick={{ fill: AXIS_TICK, fontSize: 13 }} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} />
                  <Bar dataKey="count" fill={BAR} radius={[4, 4, 0, 0]} name="件数" />
                </BarChart>
              </ResponsiveContainer>
            )
          }
          return null
        }
        return (
          <ErrorBoundary fallback={
            <div className="fixed inset-0 z-50 bg-black/85 flex items-center justify-center">
              <div className={`${card} rounded-lg p-8 max-w-sm text-center`}>
                <p className={`${textSecondary} mb-4`}>グラフの表示中にエラーが発生しました</p>
                <button onClick={() => setExpandedChart(null)} className={`px-4 py-2 ${isLight ? 'bg-gray-200 hover:bg-gray-300 text-gray-700' : 'bg-gray-600 hover:bg-gray-500 text-white'} rounded text-sm`}>閉じる</button>
              </div>
            </div>
          }>
            <ChartModal title={titles[expandedChart] ?? expandedChart} onClose={() => setExpandedChart(null)}>
              {renderContent()}
            </ChartModal>
          </ErrorBoundary>
        )
      })()}

      {/* コートヒートマップ全画面モーダル */}
      {courtHeatOpen && (
        <ErrorBoundary fallback={
          <div className="fixed inset-0 z-50 bg-black/85 flex items-center justify-center">
            <div className={`${card} rounded-lg p-8 max-w-sm text-center`}>
              <p className={`${textSecondary} mb-4`}>ヒートマップの表示中にエラーが発生しました</p>
              <button onClick={() => setCourtHeatOpen(false)} className={`px-4 py-2 ${isLight ? 'bg-gray-200 hover:bg-gray-300 text-gray-700' : 'bg-gray-600 hover:bg-gray-500 text-white'} rounded text-sm`}>閉じる</button>
            </div>
          </div>
        }>
          <CourtHeatModal
            playerId={playerId}
            matches={matches}
            initialMatchId={heatmapMatchId}
            initialLastN={heatmapLastN}
            initialTab={heatmapTab}
            onClose={() => setCourtHeatOpen(false)}
          />
        </ErrorBoundary>
      )}

      {/* SetIntervalSummary モーダル（スコア推移クリック） */}
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
            rally={pointAnalysis.rally}
            setRallies={pointAnalysis.setRallies}
          />
        </ErrorBoundary>
      )}
    </div>
  )
}
