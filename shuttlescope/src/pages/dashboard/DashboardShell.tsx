import { useState, useMemo, useEffect, useRef } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { BarChart2, User, Award, Activity, TrendingUp, Target, FileDown } from 'lucide-react'
import { apiGet, API_BASE_URL } from '@/api/client'
import { Player, AnalysisFilters } from '@/types'
import { useAuth } from '@/hooks/useAuth'
import { useTheme } from '@/hooks/useTheme'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { DashboardTopNav } from '@/components/dashboard/DashboardTopNav'
import { SearchableSelect } from '@/components/common/SearchableSelect'
import { AdviceStrip } from '@/components/common/AdviceStrip'
import { useAutoTutorial, openTutorial } from '@/components/tutorial/useTutorial'
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
  const { t } = useTranslation()
  // 旧版は bg-gray-800 を完全ハードコードしていてライトモードでも濃紺カード
  // のままになっていた (2026-05-19 修正)。
  const isLight = useIsLightMode()
  const stars = sampleSize === undefined ? null
    : sampleSize < 500 ? '★☆☆'
    : sampleSize < 2000 ? '★★☆'
    : '★★★'

  const cls = isLight
    ? {
        card:        'bg-white border border-gray-200',
        icon:        'text-gray-600',
        label:       'text-gray-500',
        value:       'text-gray-900',
        sampleNote:  'text-gray-400',
      }
    : {
        card:        'bg-gray-800 border border-gray-700',
        icon:        'text-gray-300',
        label:       'text-gray-400',
        value:       'text-white',
        sampleNote:  'text-gray-500',
      }

  return (
    <div className={`${cls.card} rounded-lg p-4 flex items-start gap-3 min-w-0`}>
      <div className={`${cls.icon} mt-0.5 shrink-0`}>{icon}</div>
      <div className="min-w-0 flex-1">
        <p className={`text-xs ${cls.label} mb-1 truncate`} title={label}>{label}</p>
        <p className={`text-xl font-semibold ${cls.value} num-cell tabular-nums`}>
          {value !== undefined && value !== null ? value : '—'}
        </p>
        {sampleSize !== undefined && (
          <p className={`text-[10px] ${cls.sampleNote} mt-0.5 num-cell tabular-nums`}>
            {stars} {t('auto.DashboardShell.k_n_rallies', { n: sampleSize.toLocaleString() })}
          </p>
        )}
      </div>
    </div>
  )
}

const ROLE_LABELS: Record<string, string> = {
  admin: '管理者',
  analyst: 'アナリスト',
  coach: 'コーチ',
  player: '選手',
}

// ロールバッジ: 元はダーク基調しか想定していなかった hardcoded 色。
// ライトモードでも読めるよう 2 セット用意し、isLight で切替える (2026-05-19)。
// 色設計: admin だけ B_BAD (= 警告/特権操作の含意)、それ以外は無彩色 + テキスト色のみ。
// 装飾的に役割ごとに違う色を当てない (Design Language §12 装飾色禁止)。
const ROLE_BADGE_CLASS_DARK: Record<string, string> = {
  admin:   'bg-gray-800 border-red-700 text-red-300',
  analyst: 'bg-gray-800 border-gray-600 text-gray-200',
  coach:   'bg-gray-800 border-gray-600 text-gray-200',
  player:  'bg-gray-800 border-gray-600 text-gray-200',
}
const ROLE_BADGE_CLASS_LIGHT: Record<string, string> = {
  admin:   'bg-white border-red-300 text-red-700',
  analyst: 'bg-white border-gray-300 text-gray-700',
  coach:   'bg-white border-gray-300 text-gray-700',
  player:  'bg-white border-gray-300 text-gray-700',
}

// ── Main Shell ────────────────────────────────────────────────────────────────

export function DashboardShell() {
  const { t } = useTranslation()
  const { role } = useAuth()
  const { theme } = useTheme()
  const isLight = theme === 'light'
  // 初回 dashboard アクセス時に「分析画面の読み方」チュートリアルを自動起動
  // (信頼度バッジ / EPV / 伸びしろ表現 / sample size 警告の意味)
  useAutoTutorial('analysis_reading')

  // player には dashboard 全体を許可。確信のある解析 (overview / growth) のみ
  // 表示する。weakness 系 (review) や信頼性低 (advanced / research) は
  // DashboardTopNav と route 側で個別に gate するため、ここでは redirect しない。

  const dlReport = (path: string, filename: string) => {
    const token = sessionStorage.getItem('shuttlescope_token')
    const fullUrl = API_BASE_URL + path.replace(/^\/api/, '')
    fetch(fullUrl, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      .then((r) => r.blob())
      .then((blob) => {
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = filename
        a.click()
        URL.revokeObjectURL(url)
      })
  }

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

  // スライダーの両端を実データの月に合わせる
  const matchDates = useMemo(
    () => (matches.map(m => m.date).filter(Boolean) as string[]).sort(),
    [matches]
  )
  const sliderMin = useMemo(() => {
    if (!matchDates.length) return undefined
    return matchDates[0].slice(0, 7) + '-01'  // 最古の月の1日
  }, [matchDates])
  const sliderMax = useMemo(() => {
    if (!matchDates.length) return undefined
    const newest = matchDates[matchDates.length - 1]
    const [y, mo] = newest.split('-').map(Number)
    const lastDay = new Date(y, mo, 0).getDate()  // 翌月0日 = 当月末日
    return `${newest.slice(0, 7)}-${String(lastDay).padStart(2, '0')}`
  }, [matchDates])

  // 選手切り替え時: 前の選手の日付範囲が残らないようリセット
  useEffect(() => {
    setFilterDateFrom(null)
    setFilterDateTo(null)
  }, [selectedPlayerId])

  const cardBg = isLight ? 'bg-gray-50' : 'bg-gray-900'
  const borderColor = isLight ? 'border-gray-200' : 'border-gray-800'
  const textPrimary = isLight ? 'text-gray-900' : 'text-white'
  const textMuted = isLight ? 'text-gray-500' : 'text-gray-400'

  // スクロール上戻し検知 → オーバーレイ表示
  const scrollRef = useRef<HTMLDivElement>(null)
  const lastScrollTop = useRef(0)
  const [showOverlay, setShowOverlay] = useState(false)

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const onScroll = () => {
      const st = el.scrollTop
      if (st < 80) {
        setShowOverlay(false)
      } else if (st < lastScrollTop.current - 40) {
        setShowOverlay(true)
      } else if (st > lastScrollTop.current + 5) {
        setShowOverlay(false)
      }
      lastScrollTop.current = st
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [])

  return (
    <div className={`relative flex flex-col h-full ${cardBg} ${textPrimary}`}>
      {/* スクロール上戻しオーバーレイ */}
      {showOverlay && selectedPlayerId && (
        <div className={`absolute top-0 left-0 right-0 z-40 shadow-lg border-b ${borderColor} ${cardBg}`}>
          <div className={`flex items-center gap-2 px-4 py-2 border-b ${borderColor}`}>
            <User size={14} className={textMuted} />
            <span className={`text-sm font-medium ${textPrimary}`}>
              {sortedPlayers.find((p) => p.id === selectedPlayerId)?.name ?? '—'}
            </span>
            {role && (
              <span className={`inline-flex items-center px-1.5 py-0.5 rounded border text-[10px] font-medium ${(isLight ? ROLE_BADGE_CLASS_LIGHT : ROLE_BADGE_CLASS_DARK)[role] ?? (isLight ? 'bg-white border-gray-300 text-gray-700' : 'bg-gray-800 border-gray-600 text-gray-200')}`}>
                {ROLE_LABELS[role] ?? role}
              </span>
            )}
          </div>
          <DashboardTopNav />
        </div>
      )}
      <div ref={scrollRef} className="flex-1 overflow-y-auto overflow-x-hidden min-h-0">
        <div className={`px-6 pt-6 pb-4 border-b ${borderColor}`}>
          <div className="flex items-center gap-3 mb-4">
            <BarChart2 className="text-blue-400" size={20} />
            <h1 className="text-xl font-semibold">{t('nav.dashboard_title', 'ダッシュボード')}</h1>
            {role && (
              <span className={`inline-flex items-center px-2 py-0.5 rounded border text-xs font-medium ${(isLight ? ROLE_BADGE_CLASS_LIGHT : ROLE_BADGE_CLASS_DARK)[role] ?? (isLight ? 'bg-white border-gray-300 text-gray-700' : 'bg-gray-800 border-gray-600 text-gray-200')}`}>
                {ROLE_LABELS[role] ?? role}
              </span>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <User size={16} className={`${textMuted} shrink-0`} />
            <label className={`text-sm ${textMuted} shrink-0`}>{t('auto.DashboardShell.k1')}</label>
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
              emptyLabel={t('common.select_player', 'Select player')}
              placeholder={t('auto.DashboardShell.k3')}
              loading={loadingPlayers}
              className="min-w-[280px]"
            />
          </div>
        </div>

        {!selectedPlayerId ? (
          <div className="flex min-h-[40vh] items-center justify-center text-gray-500 text-sm">
            {t('common.please_select_player', '選手を選択してください')}
          </div>
        ) : (
          <>
            <div className="px-6 pt-4 pb-0">
              <div className="flex flex-wrap items-center justify-end gap-1.5">
                <FileDown size={13} className={textMuted} />
                {/* 包括レポート: 現 role が見られる解析項目を全て含む。
                   PDF = 印刷して選手+コーチが議論するための整形レポート (試合単位は除外)。
                   JSON = 試合単位データ込みの完全 dump (数値解析用)。 */}
                <button
                  onClick={() => dlReport(`/api/reports/comprehensive_pdf?player_id=${selectedPlayerId}`, `report_player${selectedPlayerId}.pdf`)}
                  title={t('auto.DashboardShell.k4')}
                  className={`text-xs px-2.5 py-1 rounded border transition-colors ${
                    isLight
                      ? 'border-gray-300 text-gray-600 hover:bg-gray-100'
                      : 'border-gray-600 text-gray-300 hover:bg-gray-700'
                  }`}
                >
                  {t('auto.DashboardShell.k7')}
                </button>
                <button
                  onClick={() => dlReport(`/api/reports/comprehensive?player_id=${selectedPlayerId}`, `report_player${selectedPlayerId}.json`)}
                  title={t('auto.DashboardShell.k5')}
                  className={`text-xs px-2.5 py-1 rounded border transition-colors ${
                    isLight
                      ? 'border-gray-300 text-gray-600 hover:bg-gray-100'
                      : 'border-gray-600 text-gray-300 hover:bg-gray-700'
                  }`}
                >
                  {t('auto.DashboardShell.k8')}
                </button>
                {/* 旧 scouting / growth は残しておく (短い要約版が欲しい場合) */}
                {(role === 'admin' || role === 'analyst' || role === 'coach') && (
                  <button
                    onClick={() => dlReport(`/api/reports/scouting?player_id=${selectedPlayerId}`, `scouting_${selectedPlayerId}.pdf`)}
                    title={t('auto.DashboardShell.k6')}
                    className={`text-xs px-2.5 py-1 rounded border transition-colors ${
                      isLight
                        ? 'border-gray-300 text-gray-500 hover:bg-gray-100 opacity-70'
                        : 'border-gray-600 text-gray-400 hover:bg-gray-700 opacity-70'
                    }`}
                  >
                    {t('auto.DashboardShell.k9')}
                  </button>
                )}
              </div>
            </div>

            <div className={`px-6 pt-3 pb-3 border-b ${borderColor}`}>
              <div className="grid grid-cols-1 xs:grid-cols-2 lg:grid-cols-4 gap-3">
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
                <span className={`text-xs ${textMuted} shrink-0 ml-2`}>{t('auto.DashboardShell.k2')}</span>
                <input
                  type="date"
                  className={`border text-xs rounded px-2 py-1 focus:outline-none w-32 ${isLight ? 'bg-white border-gray-300 text-gray-800' : 'bg-gray-700 border-gray-600 text-white'}`}
                  value={filterDateFrom ?? ''}
                  onChange={(e) => setFilterDateFrom(e.target.value || null)}
                />
                <span className={`text-xs ${isLight ? 'text-gray-400' : 'text-gray-500'}`}>{t('auto.DashboardShell.k10')}</span>
                <input
                  type="date"
                  className={`border text-xs rounded px-2 py-1 focus:outline-none w-32 ${isLight ? 'bg-white border-gray-300 text-gray-800' : 'bg-gray-700 border-gray-600 text-white'}`}
                  value={filterDateTo ?? ''}
                  onChange={(e) => setFilterDateTo(e.target.value || null)}
                />
                <DateRangeSlider
                  from={filterDateFrom}
                  to={filterDateTo}
                  minDate={sliderMin}
                  maxDate={sliderMax}
                  densityDates={matchDates}
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
                    {t('auto.DashboardShell.k11')}
                  </button>
                )}
              </div>
            </div>

            <DashboardTopNav />

            <div className="px-6 pt-1 pb-8">
              <ErrorBoundary>
                <Routes>
                  <Route path="/" element={<Navigate to="overview" replace />} />
                  <Route
                    path="overview"
                    element={
                      <div className="space-y-3">
                        {/* 1. ダッシュボード Overview 最上部: 実データから計算したアドバイス strip */}
                        {selectedPlayerId && (
                          <AdviceStrip
                            context={role === 'player' ? 'player.home' : 'dashboard.overview'}
                            playerId={selectedPlayerId}
                          />
                        )}
                        <DashboardOverviewPage
                          playerId={selectedPlayerId}
                          filters={filters}
                          filterApiParams={filterApiParams}
                          matches={matches}
                          loadingMatches={loadingMatches}
                        />
                      </div>
                    }
                  />
                  <Route
                    path="live"
                    element={
                      // live は player にも開放 (score 中心で weakness 薄)。
                      // 内部で role-aware に weakness 表示は抑制する想定。
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
                      role === 'player'
                        ? <Navigate to="/dashboard/overview" replace />
                        : <DashboardReviewPage
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
                      role === 'player'
                        ? <Navigate to="/dashboard/overview" replace />
                        : <DashboardAdvancedPage
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
                      role === 'player'
                        ? <Navigate to="/dashboard/overview" replace />
                        : <DashboardResearchPage
                            playerId={selectedPlayerId}
                            filters={filters}
                          />
                    }
                  />
                </Routes>
              </ErrorBoundary>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
