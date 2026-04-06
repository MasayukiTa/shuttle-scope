import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'
import { CourtDiagram } from '@/components/court/CourtDiagram'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { RoleGuard } from '@/components/common/RoleGuard'
import { apiGet } from '@/api/client'
import { Player, AnalysisFilters, DEFAULT_FILTERS } from '@/types'
import { useAuth } from '@/hooks/useAuth'
import { User, BarChart2, Activity, Target, TrendingUp, Award, Maximize2 } from 'lucide-react'
import { BAR, WIN, LOSS, TOOLTIP_STYLE as CW_TOOLTIP, AXIS_TICK, CURSOR_FILL } from '@/styles/colors'
import { ShotWinLoss } from '@/components/analysis/ShotWinLoss'
import { RallyLengthWinRate } from '@/components/analysis/RallyLengthWinRate'
import { PressurePerformance } from '@/components/analysis/PressurePerformance'
import { SetComparison } from '@/components/analysis/SetComparison'
import { TransitionMatrix } from '@/components/analysis/TransitionMatrix'
import { ScoreProgression } from '@/components/analysis/ScoreProgression'
import { WinLossComparison } from '@/components/analysis/WinLossComparison'
import { TournamentComparison } from '@/components/analysis/TournamentComparison'
import { PreLossPatterns } from '@/components/analysis/PreLossPatterns'
import { FirstReturnAnalysis } from '@/components/analysis/FirstReturnAnalysis'
import { TemporalPerformance } from '@/components/analysis/TemporalPerformance'
import { PostLongRallyStats } from '@/components/analysis/PostLongRallyStats'
import { OpponentStats } from '@/components/analysis/OpponentStats'
import { MarkovEPV } from '@/components/analysis/MarkovEPV'
import { IntervalReport } from '@/components/analysis/IntervalReport'
import { DoublesAnalysis } from '@/components/analysis/DoublesAnalysis'
import { ErrorBoundary } from '@/components/common/ErrorBoundary'
import { ChartModal } from '@/components/common/ChartModal'

// ─── Types ────────────────────────────────────────────────────────────────────

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

interface ShotTypeRow {
  shot_type: string
  count: number
  win_rate: number
}

interface HeatmapResponse {
  success: boolean
  data: Record<string, number>
  meta?: { sample_size?: number }
}

interface MatchSummary {
  match_id: number
  opponent: string
  tournament: string
  tournament_level: string
  date: string
  result: 'win' | 'loss' | string
  rally_count: number
  format: string
}

// タブ種別
type TabKey = 'overview' | 'shots' | 'rally' | 'matrix' | 'b_detail' | 'c_spatial' | 'd_time' | 'e_opponent' | 'f_doubles' | 'g_markov'

// ─── Helpers ──────────────────────────────────────────────────────────────────

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

const TOOLTIP_STYLE = CW_TOOLTIP

function pct(value: number): string {
  return `${(value * 100).toFixed(1)}%`
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function StatCard({
  icon,
  label,
  value,
  sampleSize,
}: {
  icon: React.ReactNode
  label: string
  value: string | number | undefined
  sampleSize?: number
}) {
  // 信頼度判定
  const stars = sampleSize === undefined ? null
    : sampleSize < 500 ? '★☆☆'
    : sampleSize < 2000 ? '★★☆'
    : '★★★'

  return (
    <div className="bg-gray-800 rounded-lg p-4 flex items-start gap-3">
      <div className="text-blue-400 mt-0.5">{icon}</div>
      <div>
        <p className="text-xs text-gray-400 mb-1">{label}</p>
        <p className="text-xl font-semibold text-white">
          {value !== undefined && value !== null ? value : '—'}
        </p>
        {sampleSize !== undefined && (
          <p className="text-[10px] text-gray-500 mt-0.5">
            {stars} N={sampleSize.toLocaleString()}ラリー
          </p>
        )}
      </div>
    </div>
  )
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-sm font-semibold text-gray-300 mb-0">{children}</h2>
  )
}

function ExpandBtn({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      title="全画面で表示"
      className="shrink-0 text-gray-500 hover:text-gray-200 transition-colors p-1 rounded hover:bg-gray-700"
    >
      <Maximize2 size={13} />
    </button>
  )
}

function LoadingRow() {
  return (
    <div className="text-gray-500 text-sm py-4 text-center">読み込み中...</div>
  )
}

// タブボタン
function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2 rounded text-sm font-medium transition-colors ${
        active
          ? 'bg-blue-600 text-white'
          : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
      }`}
    >
      {children}
    </button>
  )
}

// ─── Main Component ───────────────────────────────────────────────────────────

// ロールラベルマップ
const ROLE_LABELS: Record<string, string> = {
  analyst: 'アナリスト',
  coach: 'コーチ',
  player: '選手',
}

const ROLE_BADGE_CLASS: Record<string, string> = {
  analyst: 'bg-blue-900/50 border-blue-500 text-blue-300',
  coach: 'bg-emerald-900/50 border-emerald-500 text-emerald-300',
  player: 'bg-purple-900/50 border-purple-500 text-purple-300',
}

export function DashboardPage() {
  const { t } = useTranslation()
  const { role } = useAuth()
  const navigate = useNavigate()
  const [selectedPlayerId, setSelectedPlayerId] = useState<number | null>(null)
  const [heatmapTab, setHeatmapTab] = useState<'hit' | 'land'>('hit')
  const [activeTab, setActiveTab] = useState<TabKey>('overview')
  // J-001: フィルターパネルの状態
  const [filterResult, setFilterResult] = useState<'all' | 'win' | 'loss'>('all')
  const [filterOpponent, setFilterOpponent] = useState<number | null>(null)
  const [filterLevel, setFilterLevel] = useState<string | null>(null)
  const [filterDateFrom, setFilterDateFrom] = useState<string | null>(null)
  const [filterDateTo, setFilterDateTo] = useState<string | null>(null)

  // フィルターオブジェクト（全サブコンポーネントへ渡す）
  const filters: AnalysisFilters = {
    result: filterResult,
    tournamentLevel: filterLevel,
    dateFrom: filterDateFrom,
    dateTo: filterDateTo,
  }
  // インターバルレポート用に試合を選択
  const [selectedMatchId, setSelectedMatchId] = useState<number | null>(null)
  const [intervalSet, setIntervalSet] = useState<number>(1)

  // M-002: スコア推移クリック → アノテーターへシーク
  const handleRallyClick = useCallback((rallyId: number, timestamp: number) => {
    if (!selectedMatchId) return
    if (!window.confirm(`ラリー ${rallyId} の位置（${timestamp.toFixed(1)}秒）をアノテーターで開きますか？`)) return
    navigate(`/annotator/${selectedMatchId}?seek=${timestamp}`)
  }, [selectedMatchId, navigate])
  const [showIntervalModal, setShowIntervalModal] = useState(false)
  // 全画面グラフ表示
  const [expandedChart, setExpandedChart] = useState<string | null>(null)

  // ── Players ──
  const { data: playersResp, isLoading: loadingPlayers } = useQuery({
    queryKey: ['players'],
    queryFn: () => apiGet<{ success: boolean; data: Player[] }>('/players'),
  })

  const players: Player[] = playersResp?.data ?? []
  // 試合があるプレイヤーのみ表示。対象フラグ優先 → 試合数降順 → 名前順
  const sortedPlayers = [...players]
    .filter((p) => (p.match_count ?? 0) > 0)
    .sort((a, b) => {
      if (a.is_target && !b.is_target) return -1
      if (!a.is_target && b.is_target) return 1
      return (b.match_count ?? 0) - (a.match_count ?? 0) || a.name.localeCompare(b.name, 'ja')
    })

  // フィルターAPIパラメータ（undefined値を除外）
  const filterApiParams = {
    ...(filters.result !== 'all' ? { result: filters.result } : {}),
    ...(filters.tournamentLevel ? { tournament_level: filters.tournamentLevel } : {}),
    ...(filters.dateFrom ? { date_from: filters.dateFrom } : {}),
    ...(filters.dateTo ? { date_to: filters.dateTo } : {}),
  }

  // ── Descriptive ──
  const { data: descriptiveResp, isLoading: loadingDescriptive } = useQuery({
    queryKey: ['analysis-descriptive', selectedPlayerId, filters],
    queryFn: () =>
      apiGet<{ success: boolean; data: DescriptiveData; meta?: { sample_size?: number } }>(
        '/analysis/descriptive',
        { player_id: selectedPlayerId!, ...filterApiParams }
      ),
    enabled: !!selectedPlayerId,
  })

  const descriptive: DescriptiveData | null = descriptiveResp?.data ?? null

  // ── Heatmap hit ──
  const { data: heatmapHitResp, isLoading: loadingHeatmapHit } = useQuery({
    queryKey: ['analysis-heatmap-hit', selectedPlayerId, filters],
    queryFn: () =>
      apiGet<HeatmapResponse>(
        '/analysis/heatmap',
        { player_id: selectedPlayerId!, type: 'hit', ...filterApiParams }
      ),
    enabled: !!selectedPlayerId,
  })

  // ── Heatmap land ──
  const { data: heatmapLandResp, isLoading: loadingHeatmapLand } = useQuery({
    queryKey: ['analysis-heatmap-land', selectedPlayerId, filters],
    queryFn: () =>
      apiGet<HeatmapResponse>(
        '/analysis/heatmap',
        { player_id: selectedPlayerId!, type: 'land', ...filterApiParams }
      ),
    enabled: !!selectedPlayerId,
  })

  const heatmapHit: Record<string, number> = heatmapHitResp?.data ?? {}
  const heatmapLand: Record<string, number> = heatmapLandResp?.data ?? {}

  // ── Shot types ──
  const { data: shotTypesResp, isLoading: loadingShotTypes } = useQuery({
    queryKey: ['analysis-shot-types', selectedPlayerId, filters],
    queryFn: () =>
      apiGet<{ success: boolean; data: ShotTypeRow[] }>(
        '/analysis/shot_types',
        { player_id: selectedPlayerId!, ...filterApiParams }
      ),
    enabled: !!selectedPlayerId,
  })

  const shotTypes: ShotTypeRow[] = shotTypesResp?.data ?? []
  const topShotTypes = [...shotTypes]
    .sort((a, b) => b.count - a.count)
    .slice(0, 10)

  // ── Matches summary ──
  const { data: matchesResp, isLoading: loadingMatches } = useQuery({
    queryKey: ['analysis-matches-summary', selectedPlayerId],
    queryFn: () =>
      apiGet<{ success: boolean; data: MatchSummary[] }>(
        '/analysis/matches_summary',
        { player_id: selectedPlayerId! }
      ),
    enabled: !!selectedPlayerId,
  })

  const matches: MatchSummary[] = matchesResp?.data ?? []

  // フィルター即時適用（クライアントサイド）
  const filteredMatches = matches.filter((m) => {
    if (filterResult !== 'all' && m.result !== filterResult) return false
    if (filterLevel && m.tournament_level !== filterLevel) return false
    return true
  })

  // ── End type chart data ──
  const endTypeData = descriptive
    ? Object.entries(descriptive.end_type_distribution).map(([key, count]) => ({
        name: END_TYPE_LABELS[key] ?? key,
        count,
      }))
    : []

  // ── Rally length histogram (max 20) ──
  const rallyHistData = descriptive
    ? descriptive.rally_length_histogram
        .filter((d) => d.length <= 20)
        .map((d) => ({ name: String(d.length), count: d.count }))
    : []

  // ── Shot type chart data（日本語ラベルに変換）──
  const shotChartData = topShotTypes.map((d) => ({
    name: t(`shot_types.${d.shot_type}`, d.shot_type),
    count: d.count,
  }))
  const shotSampleSize = shotTypes.reduce((sum, r) => sum + r.count, 0)

  // 選手変更時はタブをリセットしない（概要を維持する）
  function handlePlayerChange(id: number | null) {
    setSelectedPlayerId(id)
  }

  return (
    <div className="flex flex-col h-full bg-gray-900 text-white overflow-y-auto">
      {/* ── Header ── */}
      <div className="px-6 pt-6 pb-4 border-b border-gray-800">
        <div className="flex items-center gap-3 mb-4">
          <BarChart2 className="text-blue-400" size={20} />
          <h1 className="text-xl font-semibold">{t('nav.dashboard', '解析ダッシュボード')}</h1>
          {role && (
            <span
              className={`inline-flex items-center px-2 py-0.5 rounded border text-xs font-medium ${
                ROLE_BADGE_CLASS[role] ?? 'bg-gray-700 border-gray-500 text-gray-300'
              }`}
            >
              {ROLE_LABELS[role] ?? role}
            </span>
          )}
        </div>

        {/* 選手セレクター */}
        <div className="flex items-center gap-3">
          <User size={16} className="text-gray-400 shrink-0" />
          <label className="text-sm text-gray-400 shrink-0">選手：</label>
          {loadingPlayers ? (
            <span className="text-gray-500 text-sm">読み込み中...</span>
          ) : (
            <select
              className="bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500 min-w-[260px]"
              value={selectedPlayerId ?? ''}
              onChange={(e) =>
                handlePlayerChange(e.target.value ? Number(e.target.value) : null)
              }
            >
              <option value="">— 選手を選択 —</option>
              {sortedPlayers.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.is_target ? '★ ' : ''}{p.name}
                  {p.team ? `（${p.team}）` : ''}
                  {` [${p.match_count ?? 0}試合]`}
                </option>
              ))}
            </select>
          )}
        </div>
      </div>

      {/* ── Body ── */}
      {!selectedPlayerId ? (
        <div className="flex-1 flex items-center justify-center text-gray-500 text-sm">
          選手を選択してください
        </div>
      ) : loadingDescriptive ? (
        <div className="flex-1 flex items-center justify-center text-gray-500 text-sm">
          読み込み中...
        </div>
      ) : (
        <div className="px-6 py-5 space-y-5">
          {/* ── 統計カード（全タブ共通） ── */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <StatCard
              icon={<Award size={18} />}
              label="試合数"
              value={descriptive?.total_matches}
            />
            <StatCard
              icon={<Activity size={18} />}
              label="ラリー数"
              value={descriptive?.total_rallies}
              sampleSize={descriptive?.total_rallies}
            />
            <StatCard
              icon={<TrendingUp size={18} />}
              label="勝率"
              value={
                descriptive?.win_rate !== undefined
                  ? pct(descriptive.win_rate)
                  : undefined
              }
              sampleSize={descriptive?.total_rallies}
            />
            <StatCard
              icon={<Target size={18} />}
              label="平均ラリー長"
              value={
                descriptive?.avg_rally_length !== undefined
                  ? descriptive.avg_rally_length.toFixed(1)
                  : undefined
              }
              sampleSize={descriptive?.total_rallies}
            />
          </div>

          {/* ── J-001: フィルターパネル ── */}
          <div className="flex gap-2 flex-wrap items-center bg-gray-800/50 rounded-lg px-3 py-2">
            <span className="text-xs text-gray-400 shrink-0">{t('analysis.filter.result')}:</span>
            <select
              className="bg-gray-700 border border-gray-600 text-white text-xs rounded px-2 py-1 focus:outline-none"
              value={filterResult}
              onChange={(e) => setFilterResult(e.target.value as 'all' | 'win' | 'loss')}
            >
              <option value="all">{t('analysis.filter.all')}</option>
              <option value="win">{t('analysis.filter.win')}</option>
              <option value="loss">{t('analysis.filter.loss')}</option>
            </select>
            <span className="text-xs text-gray-400 shrink-0 ml-2">{t('analysis.filter.level')}:</span>
            <select
              className="bg-gray-700 border border-gray-600 text-white text-xs rounded px-2 py-1 focus:outline-none"
              value={filterLevel ?? ''}
              onChange={(e) => setFilterLevel(e.target.value || null)}
            >
              <option value="">{t('analysis.filter.all_levels')}</option>
              {['IC', 'IS', 'SJL', '全日本', '国内', 'その他'].map((lv) => (
                <option key={lv} value={lv}>{lv}</option>
              ))}
            </select>
            <span className="text-xs text-gray-400 shrink-0 ml-2">期間:</span>
            <input
              type="date"
              className="bg-gray-700 border border-gray-600 text-white text-xs rounded px-2 py-1 focus:outline-none w-32"
              value={filterDateFrom ?? ''}
              onChange={(e) => setFilterDateFrom(e.target.value || null)}
            />
            <span className="text-xs text-gray-500">〜</span>
            <input
              type="date"
              className="bg-gray-700 border border-gray-600 text-white text-xs rounded px-2 py-1 focus:outline-none w-32"
              value={filterDateTo ?? ''}
              onChange={(e) => setFilterDateTo(e.target.value || null)}
            />
            {(filterResult !== 'all' || filterLevel || filterDateFrom || filterDateTo) && (
              <button
                className="text-xs text-blue-400 hover:text-blue-300 ml-1"
                onClick={() => {
                  setFilterResult('all')
                  setFilterLevel(null)
                  setFilterOpponent(null)
                  setFilterDateFrom(null)
                  setFilterDateTo(null)
                }}
              >
                リセット
              </button>
            )}
          </div>

          {/* ── タブナビゲーション ── */}
          <div className="flex gap-2 flex-wrap">
            <TabButton active={activeTab === 'overview'} onClick={() => setActiveTab('overview')}>
              {t('analysis.overview')}
            </TabButton>
            <TabButton active={activeTab === 'shots'} onClick={() => setActiveTab('shots')}>
              {t('analysis.shots')}
            </TabButton>
            <TabButton active={activeTab === 'rally'} onClick={() => setActiveTab('rally')}>
              {t('analysis.rally')}
            </TabButton>
            <TabButton active={activeTab === 'matrix'} onClick={() => setActiveTab('matrix')}>
              {t('analysis.matrix')}
            </TabButton>
            <TabButton active={activeTab === 'b_detail'} onClick={() => setActiveTab('b_detail')}>
              {t('analysis.b_detail')}
            </TabButton>
            <TabButton active={activeTab === 'c_spatial'} onClick={() => setActiveTab('c_spatial')}>
              {t('analysis.c_spatial')}
            </TabButton>
            <TabButton active={activeTab === 'd_time'} onClick={() => setActiveTab('d_time')}>
              {t('analysis.d_time')}
            </TabButton>
            <RoleGuard allowedRoles={['analyst', 'coach']}>
              <TabButton active={activeTab === 'e_opponent'} onClick={() => setActiveTab('e_opponent')}>
                {t('analysis.e_opponent')}
              </TabButton>
            </RoleGuard>
            <TabButton active={activeTab === 'f_doubles'} onClick={() => setActiveTab('f_doubles')}>
              {t('analysis.f_doubles')}
            </TabButton>
            <RoleGuard allowedRoles={['analyst', 'coach']}>
              <TabButton active={activeTab === 'g_markov'} onClick={() => setActiveTab('g_markov')}>
                {t('analysis.g_markov')}
              </TabButton>
            </RoleGuard>
          </div>

          {/* ── 概要タブ ── */}
          {activeTab === 'overview' && (
            <ErrorBoundary>
            <div className="space-y-5">
              {/* 2カラムレイアウト */}
              <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
                {/* 左カラム（広め） */}
                <div className="xl:col-span-2 space-y-5">
                  {/* ラリー終了タイプ */}
                  <div className="bg-gray-800 rounded-lg p-4">
                    <div className="flex items-center justify-between mb-3">
                      <SectionTitle>ラリー終了タイプ</SectionTitle>
                      <div className="flex items-center gap-2">
                        {descriptive && (
                          <ConfidenceBadge sampleSize={descriptive.total_rallies} className="text-[10px] shrink-0" />
                        )}
                        <ExpandBtn onClick={() => setExpandedChart('end_type')} />
                      </div>
                    </div>
                    {loadingDescriptive ? (
                      <LoadingRow />
                    ) : endTypeData.length === 0 ? (
                      <p className="text-gray-500 text-sm text-center py-4">データなし</p>
                    ) : (
                      <ResponsiveContainer width="100%" height={200}>
                        <BarChart
                          data={endTypeData}
                          layout="vertical"
                          margin={{ top: 0, right: 16, left: 8, bottom: 0 }}
                        >
                          <XAxis type="number" tick={{ fill: '#9ca3af', fontSize: 11 }} />
                          <YAxis
                            type="category"
                            dataKey="name"
                            width={80}
                            tick={{ fill: '#9ca3af', fontSize: 11 }}
                          />
                          <Tooltip
                            contentStyle={TOOLTIP_STYLE}
                            labelStyle={{ color: '#f9fafb' }}
                            cursor={{ fill: 'rgba(255,255,255,0.05)' }}
                          />
                          <Bar dataKey="count" fill={BAR} radius={[0, 3, 3, 0]} name="件数" />
                        </BarChart>
                      </ResponsiveContainer>
                    )}
                  </div>

                  {/* ショットタイプ分布 */}
                  <div className="bg-gray-800 rounded-lg p-4">
                    <div className="flex items-center justify-between mb-3">
                      <SectionTitle>ショットタイプ分布（上位10件）</SectionTitle>
                      <div className="flex items-center gap-2">
                        {shotSampleSize > 0 && (
                          <ConfidenceBadge sampleSize={shotSampleSize} className="text-[10px] shrink-0" />
                        )}
                        <ExpandBtn onClick={() => setExpandedChart('shot_type')} />
                      </div>
                    </div>
                    {loadingShotTypes ? (
                      <LoadingRow />
                    ) : shotChartData.length === 0 ? (
                      <p className="text-gray-500 text-sm text-center py-4">データなし</p>
                    ) : (
                      <ResponsiveContainer width="100%" height={200}>
                        <BarChart
                          data={shotChartData}
                          layout="vertical"
                          margin={{ top: 0, right: 16, left: 8, bottom: 0 }}
                        >
                          <XAxis type="number" tick={{ fill: '#9ca3af', fontSize: 11 }} />
                          <YAxis
                            type="category"
                            dataKey="name"
                            width={90}
                            tick={{ fill: '#9ca3af', fontSize: 11 }}
                          />
                          <Tooltip
                            contentStyle={TOOLTIP_STYLE}
                            labelStyle={{ color: '#f9fafb' }}
                            cursor={{ fill: 'rgba(255,255,255,0.05)' }}
                          />
                          <Bar dataKey="count" fill={BAR} radius={[0, 3, 3, 0]} name="件数" />
                        </BarChart>
                      </ResponsiveContainer>
                    )}
                  </div>

                  {/* ラリー長分布 */}
                  <div className="bg-gray-800 rounded-lg p-4">
                    <div className="flex items-center justify-between mb-3">
                      <SectionTitle>ラリー長分布（〜20打）</SectionTitle>
                      <div className="flex items-center gap-2">
                        {descriptive && (
                          <ConfidenceBadge sampleSize={descriptive.total_rallies} className="text-[10px] shrink-0" />
                        )}
                        <ExpandBtn onClick={() => setExpandedChart('rally_dist')} />
                      </div>
                    </div>
                    {loadingDescriptive ? (
                      <LoadingRow />
                    ) : rallyHistData.length === 0 ? (
                      <p className="text-gray-500 text-sm text-center py-4">データなし</p>
                    ) : (
                      <ResponsiveContainer width="100%" height={200}>
                        <BarChart
                          data={rallyHistData}
                          margin={{ top: 0, right: 8, left: 0, bottom: 0 }}
                        >
                          <XAxis
                            dataKey="name"
                            tick={{ fill: '#9ca3af', fontSize: 11 }}
                            label={{
                              value: '打数',
                              position: 'insideBottomRight',
                              offset: -4,
                              fill: '#6b7280',
                              fontSize: 10,
                            }}
                          />
                          <YAxis tick={{ fill: '#9ca3af', fontSize: 11 }} />
                          <Tooltip
                            contentStyle={TOOLTIP_STYLE}
                            labelStyle={{ color: '#f9fafb' }}
                            cursor={{ fill: 'rgba(255,255,255,0.05)' }}
                          />
                          <Bar dataKey="count" fill={BAR} radius={[3, 3, 0, 0]} name="件数" />
                        </BarChart>
                      </ResponsiveContainer>
                    )}
                  </div>
                </div>

                {/* 右カラム（狭め） */}
                <div className="space-y-5">
                  {/* コートヒートマップ */}
                  <div className="bg-gray-800 rounded-lg p-4">
                    <div className="flex items-center justify-between mb-3">
                      <SectionTitle>コートヒートマップ</SectionTitle>
                      <div className="flex items-center gap-2">
                      {(() => {
                        const s = heatmapTab === 'hit'
                          ? heatmapHitResp?.meta?.sample_size
                          : heatmapLandResp?.meta?.sample_size
                        return s != null && s > 0
                          ? <ConfidenceBadge sampleSize={s} className="text-[10px] shrink-0" />
                          : null
                      })()}
                      <ExpandBtn onClick={() => setExpandedChart('court_heat')} />
                      </div>
                    </div>

                    <div className="flex gap-1 mb-3">
                      {(['hit', 'land'] as const).map((tab) => (
                        <button
                          key={tab}
                          onClick={() => setHeatmapTab(tab)}
                          className={`flex-1 text-xs py-1.5 rounded font-medium transition-colors ${
                            heatmapTab === tab
                              ? 'bg-blue-600 text-white'
                              : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
                          }`}
                        >
                          {tab === 'hit' ? '打点' : '着地点'}
                        </button>
                      ))}
                    </div>

                    {(heatmapTab === 'hit' ? loadingHeatmapHit : loadingHeatmapLand) ? (
                      <LoadingRow />
                    ) : (
                      <div className="flex justify-center">
                        <CourtDiagram
                          mode={heatmapTab}
                          heatmapData={heatmapTab === 'hit' ? heatmapHit : heatmapLand}
                          interactive={false}
                          selectedZone={null}
                          onZoneSelect={() => {}}
                          label={heatmapTab === 'hit' ? '打点分布' : '着地点分布'}
                        />
                      </div>
                    )}
                  </div>

                  {/* サーブ勝率（アナリスト・コーチのみ） */}
                  <RoleGuard
                    allowedRoles={['analyst', 'coach']}
                    fallback={
                      <div className="bg-gray-800 rounded-lg p-4">
                        <p className="text-xs text-gray-500 text-center py-2">
                          ※ このコンテンツはアナリスト・コーチ向けです
                        </p>
                      </div>
                    }
                  >
                    <div className="bg-gray-800 rounded-lg p-4">
                      <div className="flex items-center justify-between mb-3">
                        <SectionTitle>サーブ勝率</SectionTitle>
                        {descriptive && (
                          <ConfidenceBadge
                            sampleSize={descriptive.total_rallies}
                            className="text-[10px] shrink-0"
                          />
                        )}
                      </div>
                      {loadingDescriptive || !descriptive?.server_win_rate ? (
                        <LoadingRow />
                      ) : (
                        <div className="space-y-3">
                          <div className="flex items-center justify-between">
                            <span className="text-sm text-gray-400">サーバー時</span>
                            <span className="text-lg font-semibold text-blue-400">
                              {pct(descriptive.server_win_rate.as_server)}
                            </span>
                          </div>
                          <div className="w-full bg-gray-700 rounded-full h-2">
                            <div
                              className="bg-blue-500 h-2 rounded-full"
                              style={{
                                width: `${(descriptive.server_win_rate.as_server * 100).toFixed(1)}%`,
                              }}
                            />
                          </div>
                          <div className="flex items-center justify-between">
                            <span className="text-sm text-gray-400">レシーバー時</span>
                            <span className="text-lg font-semibold text-emerald-400">
                              {pct(descriptive.server_win_rate.as_receiver)}
                            </span>
                          </div>
                          <div className="w-full bg-gray-700 rounded-full h-2">
                            <div
                              className="bg-emerald-500 h-2 rounded-full"
                              style={{
                                width: `${(descriptive.server_win_rate.as_receiver * 100).toFixed(1)}%`,
                              }}
                            />
                          </div>
                        </div>
                      )}
                    </div>
                  </RoleGuard>
                </div>
              </div>

              {/* 試合一覧テーブル */}
              <div className="bg-gray-800 rounded-lg p-4">
                <div className="flex items-center justify-between mb-3">
                  <SectionTitle>試合一覧</SectionTitle>
                  <span className="text-xs text-gray-500">{filteredMatches.length} / {matches.length} 試合</span>
                </div>
                {loadingMatches ? (
                  <LoadingRow />
                ) : filteredMatches.length === 0 ? (
                  <p className="text-gray-500 text-sm text-center py-4">
                    {matches.length > 0 ? 'フィルター条件に一致する試合がありません' : 'データなし'}
                  </p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-gray-400 border-b border-gray-700">
                          <th className="text-left py-2 pr-3 font-medium">対戦相手</th>
                          <th className="text-left py-2 pr-3 font-medium">大会</th>
                          <th className="text-center py-2 pr-3 font-medium">レベル</th>
                          <th className="text-left py-2 pr-3 font-medium">日付</th>
                          <th className="text-center py-2 pr-3 font-medium">結果</th>
                          <th className="text-right py-2 font-medium">ラリー数</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredMatches.map((m) => (
                          <tr
                            key={m.match_id}
                            className="border-b border-gray-700/50 hover:bg-gray-700/30 transition-colors cursor-pointer"
                            onClick={() => setSelectedMatchId(m.match_id)}
                          >
                            <td className="py-2 pr-3 text-white">{m.opponent}</td>
                            <td className="py-2 pr-3 text-gray-300 text-xs">{m.tournament}</td>
                            <td className="py-2 pr-3 text-center">
                              <span className="text-xs text-gray-400">{m.tournament_level ?? '—'}</span>
                            </td>
                            <td className="py-2 pr-3 text-gray-300 whitespace-nowrap">{m.date}</td>
                            <td className="py-2 pr-3 text-center">
                              <span
                                className={`inline-block px-2 py-0.5 rounded text-xs font-semibold ${
                                  m.result === 'win'
                                    ? 'bg-blue-900 text-blue-300'
                                    : 'bg-red-900 text-red-300'
                                }`}
                              >
                                {m.result === 'win' ? '勝' : '負'}
                              </span>
                            </td>
                            <td className="py-2 text-right text-gray-300">{m.rally_count}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              {/* B-001: スコア推移（選択した試合） */}
              {selectedMatchId && (
                <div className="bg-gray-800 rounded-lg p-4">
                  <div className="flex items-center justify-between mb-3">
                    <SectionTitle>{t('analysis.score_progression.title')}</SectionTitle>
                    <span className="text-xs text-gray-500">試合ID: {selectedMatchId}</span>
                  </div>
                  <ScoreProgression matchId={selectedMatchId} onRallyClick={handleRallyClick} />
                </div>
              )}

              {/* インターバルレポートボタン */}
              {selectedMatchId && (
                <div className="bg-gray-800 rounded-lg p-4">
                  <div className="flex items-center justify-between mb-3">
                    <SectionTitle>{t('analysis.interval_report.title')}</SectionTitle>
                    <div className="flex gap-2 items-center">
                      <label className="text-xs text-gray-400">完了セット:</label>
                      <input
                        type="number"
                        min={1}
                        max={3}
                        value={intervalSet}
                        onChange={(e) => setIntervalSet(Number(e.target.value))}
                        className="w-12 bg-gray-700 border border-gray-600 text-white text-xs rounded px-2 py-1"
                      />
                    </div>
                  </div>
                  <IntervalReport matchId={selectedMatchId} completedSet={intervalSet} />
                </div>
              )}
            </div>
            </ErrorBoundary>
          )}

          {/* ── ショット分析タブ ── */}
          {activeTab === 'shots' && (
            <ErrorBoundary>
              <RoleGuard
                allowedRoles={['analyst', 'coach']}
                fallback={
                  <div className="bg-gray-800 rounded-lg p-6 text-center text-gray-500 text-sm">
                    ショット分析はアナリスト・コーチ向けコンテンツです
                  </div>
                }
              >
                <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
                  {/* ショット別得点・失点 */}
                  <div className="bg-gray-800 rounded-lg p-4">
                    <div className="flex items-center justify-between mb-3">
                      <SectionTitle>ショット別 得点・失点</SectionTitle>
                      <ExpandBtn onClick={() => setExpandedChart('shot_win_loss')} />
                    </div>
                    <ShotWinLoss playerId={selectedPlayerId!} filters={filters} />
                  </div>

                  {/* セット別パフォーマンス */}
                  <div className="bg-gray-800 rounded-lg p-4">
                    <div className="flex items-center justify-between mb-3">
                      <SectionTitle>セット別パフォーマンス</SectionTitle>
                      <ExpandBtn onClick={() => setExpandedChart('set_comparison')} />
                    </div>
                    <SetComparison playerId={selectedPlayerId!} filters={filters} />
                  </div>
                </div>
              </RoleGuard>
            </ErrorBoundary>
          )}

          {/* ── ラリー分析タブ ── */}
          {activeTab === 'rally' && (
            <ErrorBoundary>
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
              {/* ラリー長別勝率 */}
              <div className="bg-gray-800 rounded-lg p-4">
                <div className="flex items-center justify-between mb-3">
                  <SectionTitle>ラリー長別 勝率</SectionTitle>
                  <ExpandBtn onClick={() => setExpandedChart('rally_win_rate')} />
                </div>
                <RallyLengthWinRate playerId={selectedPlayerId!} filters={filters} />
              </div>

              {/* プレッシャー下のパフォーマンス */}
              <div className="bg-gray-800 rounded-lg p-4">
                <div className="flex items-center justify-between mb-3">
                  <SectionTitle>プレッシャー下のパフォーマンス</SectionTitle>
                  <ExpandBtn onClick={() => setExpandedChart('pressure')} />
                </div>
                <PressurePerformance playerId={selectedPlayerId!} filters={filters} />
              </div>
            </div>
            </ErrorBoundary>
          )}

          {/* ── 遷移マトリクスタブ ── */}
          {activeTab === 'matrix' && (
            <ErrorBoundary>
              <RoleGuard
                allowedRoles={['analyst', 'coach']}
                fallback={
                  <div className="bg-gray-800 rounded-lg p-6 text-center text-gray-500 text-sm">
                    遷移マトリクスはアナリスト・コーチ向けコンテンツです
                  </div>
                }
              >
                <div className="bg-gray-800 rounded-lg p-4">
                  <div className="flex items-center justify-between mb-3">
                    <SectionTitle>ショット遷移マトリクス</SectionTitle>
                    <ExpandBtn onClick={() => setExpandedChart('transition')} />
                  </div>
                  <TransitionMatrix playerId={selectedPlayerId!} filters={filters} />
                </div>
              </RoleGuard>
            </ErrorBoundary>
          )}

          {/* ── 詳細分析タブ (B-001, B-004, B-006) ── */}
          {activeTab === 'b_detail' && (
            <ErrorBoundary>
              <div className="space-y-5">
                {/* スコア推移 */}
                <div className="bg-gray-800 rounded-lg p-4">
                  <div className="flex items-center justify-between mb-3">
                    <SectionTitle>{t('analysis.score_progression.title')}</SectionTitle>
                    {/* 試合セレクター */}
                    <select
                      className="text-xs bg-gray-700 border border-gray-600 text-gray-200 rounded px-2 py-1 max-w-[220px]"
                      value={selectedMatchId ?? ''}
                      onChange={(e) => setSelectedMatchId(e.target.value ? Number(e.target.value) : null)}
                    >
                      <option value="">-- 試合を選択 --</option>
                      {matches.map((m) => (
                        <option key={m.match_id} value={m.match_id}>
                          [{m.result === 'win' ? '○' : '●'}] {m.date} vs {m.opponent}{m.tournament_level ? ` (${m.tournament_level})` : ''}
                        </option>
                      ))}
                    </select>
                  </div>
                  {selectedMatchId ? (
                    <ScoreProgression matchId={selectedMatchId} onRallyClick={handleRallyClick} />
                  ) : (
                    <p className="text-gray-500 text-sm text-center py-4">
                      試合を選択するとスコア推移が表示されます
                    </p>
                  )}
                </div>

                <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
                  {/* 勝ち/課題のある試合比較 */}
                  <div className="bg-gray-800 rounded-lg p-4">
                    <SectionTitle>{t('analysis.win_loss_comparison.title')}</SectionTitle>
                    <WinLossComparison playerId={selectedPlayerId!} filters={filters} />
                  </div>

                  {/* 大会レベル別比較 */}
                  <div className="bg-gray-800 rounded-lg p-4">
                    <SectionTitle>{t('analysis.tournament_comparison.title')}</SectionTitle>
                    <TournamentComparison playerId={selectedPlayerId!} filters={filters} />
                  </div>
                </div>
              </div>
            </ErrorBoundary>
          )}

          {/* ── 空間分析タブ (C-002, C-003) ── */}
          {activeTab === 'c_spatial' && (
            <ErrorBoundary>
              <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
                <div className="bg-gray-800 rounded-lg p-4">
                  <SectionTitle>{t('analysis.pre_loss.title')}</SectionTitle>
                  <PreLossPatterns playerId={selectedPlayerId!} filters={filters} />
                </div>
                <div className="bg-gray-800 rounded-lg p-4">
                  <SectionTitle>{t('analysis.first_return.title')}</SectionTitle>
                  <FirstReturnAnalysis playerId={selectedPlayerId!} filters={filters} />
                </div>
              </div>
            </ErrorBoundary>
          )}

          {/* ── 時間・体力タブ (D-002, D-003) ── */}
          {activeTab === 'd_time' && (
            <ErrorBoundary>
              <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
                <div className="bg-gray-800 rounded-lg p-4">
                  <div className="flex items-center justify-between mb-3">
                    <SectionTitle>{t('analysis.temporal.title')}</SectionTitle>
                    <ExpandBtn onClick={() => setExpandedChart('temporal')} />
                  </div>
                  <TemporalPerformance playerId={selectedPlayerId!} filters={filters} />
                </div>
                <div className="bg-gray-800 rounded-lg p-4">
                  <div className="flex items-center justify-between mb-3">
                    <SectionTitle>{t('analysis.post_long_rally.title')}</SectionTitle>
                    <ExpandBtn onClick={() => setExpandedChart('post_long')} />
                  </div>
                  <PostLongRallyStats playerId={selectedPlayerId!} filters={filters} />
                </div>
              </div>
            </ErrorBoundary>
          )}

          {/* ── 対戦相手タブ (E-001) ── */}
          {activeTab === 'e_opponent' && (
            <ErrorBoundary>
              <RoleGuard
                allowedRoles={['analyst', 'coach']}
                fallback={
                  <div className="bg-gray-800 rounded-lg p-6 text-center text-gray-500 text-sm">
                    {t('analysis.restricted')}
                  </div>
                }
              >
                <div className="bg-gray-800 rounded-lg p-4">
                  <SectionTitle>{t('analysis.opponent_stats.title')}</SectionTitle>
                  <OpponentStats playerId={selectedPlayerId!} />
                </div>
              </RoleGuard>
            </ErrorBoundary>
          )}

          {/* ── ダブルスタブ (F-001〜F-004) ── */}
          {activeTab === 'f_doubles' && (
            <ErrorBoundary>
              <DoublesAnalysis
                playerId={selectedPlayerId!}
                allMatches={matches}
              />
            </ErrorBoundary>
          )}

          {/* ── 詳細解析タブ (G-001: MarkovEPV) ── */}
          {activeTab === 'g_markov' && (
            <ErrorBoundary>
              <RoleGuard
                allowedRoles={['analyst', 'coach']}
                fallback={
                  <div className="bg-gray-800 rounded-lg p-6 text-center text-gray-500 text-sm">
                    {t('analysis.restricted')}
                  </div>
                }
              >
                <div className="bg-gray-800 rounded-lg p-4">
                  <div className="flex items-center justify-between mb-3">
                    <SectionTitle>{t('analysis.epv.title')}</SectionTitle>
                    <ExpandBtn onClick={() => setExpandedChart('epv')} />
                  </div>
                  <MarkovEPV playerId={selectedPlayerId!} filters={filters} />
                </div>
              </RoleGuard>
            </ErrorBoundary>
          )}
        </div>
      )}

      {/* ── 全画面グラフモーダル ── */}
      {expandedChart && selectedPlayerId && (() => {
        const CHART_TITLES: Record<string, string> = {
          end_type:      'ラリー終了タイプ',
          shot_type:     'ショットタイプ分布（上位10件）',
          rally_dist:    'ラリー長分布',
          court_heat:    'コートヒートマップ',
          shot_win_loss: 'ショット別 得点・失点',
          set_comparison:'セット別パフォーマンス',
          rally_win_rate:'ラリー長別 勝率',
          pressure:      'プレッシャー下のパフォーマンス',
          transition:    'ショット遷移マトリクス',
          temporal:      '時間帯別パフォーマンス',
          post_long:     'ロングラリー後の傾向',
          epv:           '詳細解析（EPV）',
        }
        const pid = selectedPlayerId
        const renderContent = () => {
          switch (expandedChart) {
            case 'end_type': return endTypeData.length > 0 ? (
              <ResponsiveContainer width="100%" height={500}>
                <BarChart data={endTypeData} layout="vertical" margin={{ top: 0, right: 24, left: 16, bottom: 0 }}>
                  <XAxis type="number" tick={{ fill: '#9ca3af', fontSize: 13 }} />
                  <YAxis type="category" dataKey="name" width={100} tick={{ fill: '#9ca3af', fontSize: 13 }} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} />
                  <Bar dataKey="count" fill={BAR} radius={[0, 4, 4, 0]} name="件数" />
                </BarChart>
              </ResponsiveContainer>
            ) : null
            case 'shot_type': return shotChartData.length > 0 ? (
              <ResponsiveContainer width="100%" height={500}>
                <BarChart data={shotChartData} layout="vertical" margin={{ top: 0, right: 24, left: 16, bottom: 0 }}>
                  <XAxis type="number" tick={{ fill: '#9ca3af', fontSize: 13 }} />
                  <YAxis type="category" dataKey="name" width={110} tick={{ fill: '#9ca3af', fontSize: 13 }} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} />
                  <Bar dataKey="count" fill={BAR} radius={[0, 4, 4, 0]} name="件数" />
                </BarChart>
              </ResponsiveContainer>
            ) : null
            case 'rally_dist': return rallyHistData.length > 0 ? (
              <ResponsiveContainer width="100%" height={400}>
                <BarChart data={rallyHistData} margin={{ top: 0, right: 24, left: 0, bottom: 0 }}>
                  <XAxis dataKey="name" tick={{ fill: '#9ca3af', fontSize: 13 }} />
                  <YAxis tick={{ fill: '#9ca3af', fontSize: 13 }} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} />
                  <Bar dataKey="count" fill={BAR} radius={[4, 4, 0, 0]} name="件数" />
                </BarChart>
              </ResponsiveContainer>
            ) : null
            case 'court_heat': return (
              <div className="flex justify-center">
                <CourtDiagram
                  mode={heatmapTab}
                  heatmapData={heatmapTab === 'hit' ? heatmapHit : heatmapLand}
                  interactive={false}
                  selectedZone={null}
                  onZoneSelect={() => {}}
                  label={heatmapTab === 'hit' ? '打点分布' : '着地点分布'}
                  maxWidth={520}
                />
              </div>
            )
            case 'shot_win_loss':  return <ShotWinLoss playerId={pid} filters={filters} />
            case 'set_comparison': return <SetComparison playerId={pid} chartHeight={480} filters={filters} />
            case 'rally_win_rate': return <RallyLengthWinRate playerId={pid} chartHeight={500} filters={filters} />
            case 'pressure':       return <PressurePerformance playerId={pid} filters={filters} />
            case 'transition':     return <TransitionMatrix playerId={pid} filters={filters} />
            case 'temporal':       return <TemporalPerformance playerId={pid} chartHeight={480} filters={filters} />
            case 'post_long':      return <PostLongRallyStats playerId={pid} filters={filters} />
            case 'epv':            return <MarkovEPV playerId={pid} filters={filters} />
            default:               return null
          }
        }
        return (
          <ChartModal
            title={CHART_TITLES[expandedChart] ?? expandedChart}
            onClose={() => setExpandedChart(null)}
          >
            {renderContent()}
          </ChartModal>
        )
      })()}
    </div>
  )
}
