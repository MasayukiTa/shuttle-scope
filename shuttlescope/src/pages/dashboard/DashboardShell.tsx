import { useState } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { BarChart2, User, Award, Activity, TrendingUp, Target } from 'lucide-react'
import { apiGet } from '@/api/client'
import { Player, AnalysisFilters } from '@/types'
import { useAuth } from '@/hooks/useAuth'
import { useTheme } from '@/hooks/useTheme'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { DashboardTopNav } from '@/components/dashboard/DashboardTopNav'
import { SearchableSelect } from '@/components/common/SearchableSelect'
import { DashboardOverviewPage } from './DashboardOverviewPage'
import { DashboardLivePage } from './DashboardLivePage'
import { DashboardReviewPage } from './DashboardReviewPage'
import { DashboardGrowthPage } from './DashboardGrowthPage'
import { DashboardAdvancedPage } from './DashboardAdvancedPage'
import { DashboardResearchPage } from './DashboardResearchPage'
import { ErrorBoundary } from '@/components/common/ErrorBoundary'
import { DateRangeSlider } from '@/components/common/DateRangeSlider'

// ── Types ────────────────────────────────────────────────────────────────────

interface DescriptiveSummary {
  total_matches: number
  total_rallies: number
  win_rate: number
  avg_rally_length: number
  end_type_distribution: Record<string, number>
  rally_length_histogram: { length: number; count: number }[]
  win_by_end_type: Record<string, { wins: number; total: number }>
  server_win_rate: { as_server: number; as_receiver: number }
}

interface SetScore {
  set_num: number
  score_player: number
  score_opponent: number
  won: boolean
}

export interface MatchSummary {
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

// ── Helpers ──────────────────────────────────────────────────────────────────

function pct(value: number) {
  return `${(value * 100).toFixed(1)}%`
}

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

// ── Main Shell ────────────────────────────────────────────────────────────────

export function DashboardShell() {
  const { t } = useTranslation()
  const { role } = useAuth()
  const { theme } = useTheme()
  const isLight = theme === 'light'

  // ── 共有状態 ──
  const [selectedPlayerId, setSelectedPlayerId] = useState<number | null>(null)
  const [filterResult, setFilterResult] = useState<'all' | 'win' | 'loss'>('all')
  const [filterLevel, setFilterLevel] = useState<string | null>(null)
  const [filterDateFrom, setFilterDateFrom] = useState<string | null>(null)
  const [filterDateTo, setFilterDateTo] = useState<string | null>(null)

  const filters: AnalysisFilters = {
    result: filterResult,
    tournamentLevel: filterLevel,
    dateFrom: filterDateFrom,
    dateTo: filterDateTo,
  }

  const filterApiParams: Record<string, string> = {
    ...(filterResult !== 'all' ? { result: filterResult } : {}),
    ...(filterLevel ? { tournament_level: filterLevel } : {}),
    ...(filterDateFrom ? { date_from: filterDateFrom } : {}),
    ...(filterDateTo ? { date_to: filterDateTo } : {}),
  }

  // 選手が切り替わったらフィルターリセット不要だが、試合選択は各サブページで管理

  // ── Players ──
  const { data: playersResp, isLoading: loadingPlayers } = useQuery({
    queryKey: ['players'],
    queryFn: () => apiGet<{ success: boolean; data: Player[] }>('/players'),
  })
  const players: Player[] = playersResp?.data ?? []
  const sortedPlayers = [...players]
    .filter((p) => (p.match_count ?? 0) > 0)
    .sort((a, b) => {
      if (a.is_target && !b.is_target) return -1
      if (!a.is_target && b.is_target) return 1
      return (b.match_count ?? 0) - (a.match_count ?? 0) || a.name.localeCompare(b.name, 'ja')
    })

  // ── Descriptive（StatCards 用） ──
  const { data: descriptiveResp, isLoading: loadingDescriptive } = useQuery({
    queryKey: ['analysis-descriptive', selectedPlayerId, filters],
    queryFn: () =>
      apiGet<{ success: boolean; data: DescriptiveSummary }>(
        '/analysis/descriptive',
        { player_id: selectedPlayerId!, ...filterApiParams }
      ),
    enabled: !!selectedPlayerId,
  })
  const descriptive = descriptiveResp?.data ?? null

  // ── Matches（複数サブページで共有） ──
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

  const cardBg = isLight ? 'bg-gray-50' : 'bg-gray-900'
  const borderColor = isLight ? 'border-gray-200' : 'border-gray-800'
  const textPrimary = isLight ? 'text-gray-900' : 'text-white'
  const textMuted = isLight ? 'text-gray-500' : 'text-gray-400'

  return (
    <div className={`flex flex-col h-full ${cardBg} ${textPrimary} overflow-y-auto`}>
      {/* ── Header ── */}
      <div className={`px-6 pt-6 pb-4 border-b ${borderColor}`}>
        <div className="flex items-center gap-3 mb-4">
          <BarChart2 className="text-blue-400" size={20} />
          <h1 className="text-xl font-semibold">{t('nav.dashboard_title', 'ダッシュボード')}</h1>
          {role && (
            <span className={`inline-flex items-center px-2 py-0.5 rounded border text-xs font-medium ${ROLE_BADGE_CLASS[role] ?? 'bg-gray-700 border-gray-500 text-gray-300'}`}>
              {ROLE_LABELS[role] ?? role}
            </span>
          )}
        </div>

        {/* 選手セレクター */}
        <div className="flex items-center gap-3">
          <User size={16} className={`${textMuted} shrink-0`} />
          <label className={`text-sm ${textMuted} shrink-0`}>選手：</label>
          <SearchableSelect
            options={sortedPlayers.map((p) => ({
              value: p.id,
              label: p.name,
              searchText: p.team ?? '',
              prefix: p.is_target ? '★' : undefined,
              suffix: `${p.team ? `（${p.team}）` : ''} [${p.match_count ?? 0}試合]`,
            }))}
            value={selectedPlayerId}
            onChange={(v) => setSelectedPlayerId(v != null ? Number(v) : null)}
            emptyLabel="— 選手を選択 —"
            placeholder="選手名で検索..."
            loading={loadingPlayers}
            className="min-w-[280px]"
          />
        </div>
      </div>

      {/* ── Body ── */}
      {!selectedPlayerId ? (
        <div className="flex-1 flex items-center justify-center text-gray-500 text-sm">
          選手を選択してください
        </div>
      ) : (
        <div className="flex flex-col flex-1 min-h-0">
          {/* StatCards */}
          <div className={`px-6 pt-4 pb-3 border-b ${borderColor}`}>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <StatCard icon={<Award size={18} />} label="試合数" value={descriptive?.total_matches} />
              <StatCard icon={<Activity size={18} />} label="ラリー数" value={descriptive?.total_rallies} sampleSize={descriptive?.total_rallies} />
              <StatCard
                icon={<TrendingUp size={18} />}
                label="勝率"
                value={descriptive?.win_rate !== undefined ? pct(descriptive.win_rate) : undefined}
                sampleSize={descriptive?.total_rallies}
              />
              <StatCard
                icon={<Target size={18} />}
                label="平均ラリー長"
                value={descriptive?.avg_rally_length !== undefined ? descriptive.avg_rally_length.toFixed(1) : undefined}
                sampleSize={descriptive?.total_rallies}
              />
            </div>
          </div>

          {/* フィルターパネル */}
          <div className={`px-6 py-2 border-b ${borderColor}`}>
            <div className={`flex gap-2 flex-wrap items-center rounded-lg px-3 py-2 ${isLight ? 'bg-gray-100' : 'bg-gray-800/50'}`}>
              <span className={`text-xs ${textMuted} shrink-0`}>{t('analysis.filter.result')}:</span>
              <select
                className={`border text-xs rounded px-2 py-1 focus:outline-none ${isLight ? 'bg-white border-gray-300 text-gray-800' : 'bg-gray-700 border-gray-600 text-white'}`}
                value={filterResult}
                onChange={(e) => setFilterResult(e.target.value as 'all' | 'win' | 'loss')}
              >
                <option value="all">{t('analysis.filter.all')}</option>
                <option value="win">{t('analysis.filter.win')}</option>
                <option value="loss">{t('analysis.filter.loss')}</option>
              </select>
              <span className={`text-xs ${textMuted} shrink-0 ml-2`}>{t('analysis.filter.level')}:</span>
              <select
                className={`border text-xs rounded px-2 py-1 focus:outline-none ${isLight ? 'bg-white border-gray-300 text-gray-800' : 'bg-gray-700 border-gray-600 text-white'}`}
                value={filterLevel ?? ''}
                onChange={(e) => setFilterLevel(e.target.value || null)}
              >
                <option value="">{t('analysis.filter.all_levels')}</option>
                {['IC', 'IS', 'SJL', '全日本', '国内', 'その他'].map((lv) => (
                  <option key={lv} value={lv}>{lv}</option>
                ))}
              </select>
              <span className={`text-xs ${textMuted} shrink-0 ml-2`}>期間:</span>
              <input
                type="date"
                className={`border text-xs rounded px-2 py-1 focus:outline-none w-32 ${isLight ? 'bg-white border-gray-300 text-gray-800' : 'bg-gray-700 border-gray-600 text-white'}`}
                value={filterDateFrom ?? ''}
                onChange={(e) => setFilterDateFrom(e.target.value || null)}
              />
              <span className={`text-xs ${isLight ? 'text-gray-400' : 'text-gray-500'}`}>〜</span>
              <input
                type="date"
                className={`border text-xs rounded px-2 py-1 focus:outline-none w-32 ${isLight ? 'bg-white border-gray-300 text-gray-800' : 'bg-gray-700 border-gray-600 text-white'}`}
                value={filterDateTo ?? ''}
                onChange={(e) => setFilterDateTo(e.target.value || null)}
              />
              <DateRangeSlider
                from={filterDateFrom}
                to={filterDateTo}
                densityDates={matches.map(m => m.date).filter(Boolean) as string[]}
                onChange={(f, t) => { setFilterDateFrom(f); setFilterDateTo(t) }}
                isLight={isLight}
              />
              {(filterResult !== 'all' || filterLevel || filterDateFrom || filterDateTo) && (
                <button
                  className="text-xs text-blue-400 hover:text-blue-300 ml-1"
                  onClick={() => {
                    setFilterResult('all')
                    setFilterLevel(null)
                    setFilterDateFrom(null)
                    setFilterDateTo(null)
                  }}
                >
                  リセット
                </button>
              )}
            </div>
          </div>

          {/* サブページナビ */}
          <DashboardTopNav />

          {/* サブページコンテンツ */}
          <div className="flex-1 overflow-y-auto px-6 py-5">
            <ErrorBoundary>
              <Routes>
                <Route path="/" element={<Navigate to="overview" replace />} />
                <Route
                  path="overview"
                  element={
                    <DashboardOverviewPage
                      playerId={selectedPlayerId}
                      filters={filters}
                      filterApiParams={filterApiParams}
                      matches={matches}
                      loadingMatches={loadingMatches}
                    />
                  }
                />
                <Route
                  path="live"
                  element={
                    <DashboardLivePage
                      playerId={selectedPlayerId}
                      filters={filters}
                      matches={matches}
                    />
                  }
                />
                <Route
                  path="review"
                  element={
                    <DashboardReviewPage
                      playerId={selectedPlayerId}
                      filters={filters}
                      matches={matches}
                    />
                  }
                />
                <Route
                  path="growth"
                  element={
                    <DashboardGrowthPage
                      playerId={selectedPlayerId}
                      filters={filters}
                      sortedPlayers={sortedPlayers}
                    />
                  }
                />
                <Route
                  path="advanced"
                  element={
                    <DashboardAdvancedPage
                      playerId={selectedPlayerId}
                      filters={filters}
                      matches={matches}
                      sortedPlayers={sortedPlayers}
                    />
                  }
                />
                <Route
                  path="research"
                  element={
                    <DashboardResearchPage
                      playerId={selectedPlayerId}
                      filters={filters}
                    />
                  }
                />
              </Routes>
            </ErrorBoundary>
          </div>
        </div>
      )}
    </div>
  )
}
