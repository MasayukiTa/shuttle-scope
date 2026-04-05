import { useState } from 'react'
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
import { apiGet } from '@/api/client'
import { Player } from '@/types'
import { User, BarChart2, Activity, Target, TrendingUp, Award } from 'lucide-react'
import { ShotWinLoss } from '@/components/analysis/ShotWinLoss'
import { RallyLengthWinRate } from '@/components/analysis/RallyLengthWinRate'
import { PressurePerformance } from '@/components/analysis/PressurePerformance'
import { SetComparison } from '@/components/analysis/SetComparison'
import { TransitionMatrix } from '@/components/analysis/TransitionMatrix'
import { ErrorBoundary } from '@/components/common/ErrorBoundary'

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

interface MatchSummary {
  match_id: number
  opponent: string
  tournament: string
  date: string
  result: 'win' | 'loss' | string
  rally_count: number
}

// タブ種別
type TabKey = 'overview' | 'shots' | 'rally' | 'matrix'

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

const TOOLTIP_STYLE = {
  backgroundColor: '#1f2937',
  border: '1px solid #374151',
  borderRadius: '6px',
  color: '#f9fafb',
}

function pct(value: number): string {
  return `${(value * 100).toFixed(1)}%`
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function StatCard({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode
  label: string
  value: string | number | undefined
}) {
  return (
    <div className="bg-gray-800 rounded-lg p-4 flex items-start gap-3">
      <div className="text-blue-400 mt-0.5">{icon}</div>
      <div>
        <p className="text-xs text-gray-400 mb-1">{label}</p>
        <p className="text-xl font-semibold text-white">
          {value !== undefined && value !== null ? value : '—'}
        </p>
      </div>
    </div>
  )
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-sm font-semibold text-gray-300 mb-3">{children}</h2>
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

export function DashboardPage() {
  const { t } = useTranslation()
  const [selectedPlayerId, setSelectedPlayerId] = useState<number | null>(null)
  const [heatmapTab, setHeatmapTab] = useState<'hit' | 'land'>('hit')
  const [activeTab, setActiveTab] = useState<TabKey>('overview')

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

  // ── Descriptive ──
  const { data: descriptiveResp, isLoading: loadingDescriptive } = useQuery({
    queryKey: ['analysis-descriptive', selectedPlayerId],
    queryFn: () =>
      apiGet<{ success: boolean; data: DescriptiveData; meta?: { sample_size?: number } }>(
        '/analysis/descriptive',
        { player_id: selectedPlayerId! }
      ),
    enabled: !!selectedPlayerId,
  })

  const descriptive: DescriptiveData | null = descriptiveResp?.data ?? null

  // ── Heatmap hit ──
  const { data: heatmapHitResp, isLoading: loadingHeatmapHit } = useQuery({
    queryKey: ['analysis-heatmap-hit', selectedPlayerId],
    queryFn: () =>
      apiGet<{ success: boolean; data: Record<string, number> }>(
        '/analysis/heatmap',
        { player_id: selectedPlayerId!, type: 'hit' }
      ),
    enabled: !!selectedPlayerId,
  })

  // ── Heatmap land ──
  const { data: heatmapLandResp, isLoading: loadingHeatmapLand } = useQuery({
    queryKey: ['analysis-heatmap-land', selectedPlayerId],
    queryFn: () =>
      apiGet<{ success: boolean; data: Record<string, number> }>(
        '/analysis/heatmap',
        { player_id: selectedPlayerId!, type: 'land' }
      ),
    enabled: !!selectedPlayerId,
  })

  const heatmapHit: Record<string, number> = heatmapHitResp?.data ?? {}
  const heatmapLand: Record<string, number> = heatmapLandResp?.data ?? {}

  // ── Shot types ──
  const { data: shotTypesResp, isLoading: loadingShotTypes } = useQuery({
    queryKey: ['analysis-shot-types', selectedPlayerId],
    queryFn: () =>
      apiGet<{ success: boolean; data: ShotTypeRow[] }>(
        '/analysis/shot_types',
        { player_id: selectedPlayerId! }
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

  // ── Shot type chart data ──
  const shotChartData = topShotTypes.map((d) => ({
    name: d.shot_type,
    count: d.count,
  }))

  // 選手変更時はタブをリセットしない（概要を維持する）
  function handlePlayerChange(id: number | null) {
    setSelectedPlayerId(id)
  }

  return (
    <div className="flex flex-col h-full bg-gray-900 text-white overflow-y-auto">
      {/* ── Header ── */}
      <div className="px-6 pt-6 pb-4 border-b border-gray-800">
        <div className="flex items-center gap-2 mb-4">
          <BarChart2 className="text-blue-400" size={20} />
          <h1 className="text-xl font-semibold">{t('nav.dashboard', '解析ダッシュボード')}</h1>
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
            />
            <StatCard
              icon={<TrendingUp size={18} />}
              label="勝率"
              value={
                descriptive?.win_rate !== undefined
                  ? pct(descriptive.win_rate)
                  : undefined
              }
            />
            <StatCard
              icon={<Target size={18} />}
              label="平均ラリー長"
              value={
                descriptive?.avg_rally_length !== undefined
                  ? descriptive.avg_rally_length.toFixed(1)
                  : undefined
              }
            />
          </div>

          {/* ── タブナビゲーション ── */}
          <div className="flex gap-2 flex-wrap">
            <TabButton active={activeTab === 'overview'} onClick={() => setActiveTab('overview')}>
              概要
            </TabButton>
            <TabButton active={activeTab === 'shots'} onClick={() => setActiveTab('shots')}>
              ショット分析
            </TabButton>
            <TabButton active={activeTab === 'rally'} onClick={() => setActiveTab('rally')}>
              ラリー分析
            </TabButton>
            <TabButton active={activeTab === 'matrix'} onClick={() => setActiveTab('matrix')}>
              遷移マトリクス
            </TabButton>
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
                    <SectionTitle>ラリー終了タイプ</SectionTitle>
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
                          <Bar dataKey="count" fill="#3b82f6" radius={[0, 3, 3, 0]} name="件数" />
                        </BarChart>
                      </ResponsiveContainer>
                    )}
                  </div>

                  {/* ショットタイプ分布 */}
                  <div className="bg-gray-800 rounded-lg p-4">
                    <SectionTitle>ショットタイプ分布（上位10件）</SectionTitle>
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
                          <Bar dataKey="count" fill="#10b981" radius={[0, 3, 3, 0]} name="件数" />
                        </BarChart>
                      </ResponsiveContainer>
                    )}
                  </div>

                  {/* ラリー長分布 */}
                  <div className="bg-gray-800 rounded-lg p-4">
                    <SectionTitle>ラリー長分布（〜20打）</SectionTitle>
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
                          <Bar dataKey="count" fill="#3b82f6" radius={[3, 3, 0, 0]} name="件数" />
                        </BarChart>
                      </ResponsiveContainer>
                    )}
                  </div>
                </div>

                {/* 右カラム（狭め） */}
                <div className="space-y-5">
                  {/* コートヒートマップ */}
                  <div className="bg-gray-800 rounded-lg p-4">
                    <SectionTitle>コートヒートマップ</SectionTitle>

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

                  {/* サーブ勝率 */}
                  <div className="bg-gray-800 rounded-lg p-4">
                    <SectionTitle>サーブ勝率</SectionTitle>
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
                </div>
              </div>

              {/* 試合一覧テーブル */}
              <div className="bg-gray-800 rounded-lg p-4">
                <SectionTitle>試合一覧</SectionTitle>
                {loadingMatches ? (
                  <LoadingRow />
                ) : matches.length === 0 ? (
                  <p className="text-gray-500 text-sm text-center py-4">データなし</p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-gray-400 border-b border-gray-700">
                          <th className="text-left py-2 pr-4 font-medium">対戦相手</th>
                          <th className="text-left py-2 pr-4 font-medium">大会</th>
                          <th className="text-left py-2 pr-4 font-medium">日付</th>
                          <th className="text-center py-2 pr-4 font-medium">結果</th>
                          <th className="text-right py-2 font-medium">ラリー数</th>
                        </tr>
                      </thead>
                      <tbody>
                        {matches.map((m) => (
                          <tr
                            key={m.match_id}
                            className="border-b border-gray-700/50 hover:bg-gray-700/30 transition-colors"
                          >
                            <td className="py-2 pr-4 text-white">{m.opponent}</td>
                            <td className="py-2 pr-4 text-gray-300">{m.tournament}</td>
                            <td className="py-2 pr-4 text-gray-300 whitespace-nowrap">{m.date}</td>
                            <td className="py-2 pr-4 text-center">
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
            </div>
            </ErrorBoundary>
          )}

          {/* ── ショット分析タブ ── */}
          {activeTab === 'shots' && (
            <ErrorBoundary>
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
              {/* ショット別得点・失点 */}
              <div className="bg-gray-800 rounded-lg p-4">
                <SectionTitle>ショット別 得点・失点</SectionTitle>
                <ShotWinLoss playerId={selectedPlayerId!} />
              </div>

              {/* セット別パフォーマンス */}
              <div className="bg-gray-800 rounded-lg p-4">
                <SectionTitle>セット別パフォーマンス</SectionTitle>
                <SetComparison playerId={selectedPlayerId!} />
              </div>
            </div>
            </ErrorBoundary>
          )}

          {/* ── ラリー分析タブ ── */}
          {activeTab === 'rally' && (
            <ErrorBoundary>
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
              {/* ラリー長別勝率 */}
              <div className="bg-gray-800 rounded-lg p-4">
                <SectionTitle>ラリー長別 勝率</SectionTitle>
                <RallyLengthWinRate playerId={selectedPlayerId!} />
              </div>

              {/* プレッシャー下のパフォーマンス */}
              <div className="bg-gray-800 rounded-lg p-4">
                <SectionTitle>プレッシャー下のパフォーマンス</SectionTitle>
                <PressurePerformance playerId={selectedPlayerId!} />
              </div>
            </div>
            </ErrorBoundary>
          )}

          {/* ── 遷移マトリクスタブ ── */}
          {activeTab === 'matrix' && (
            <ErrorBoundary>
            <div className="bg-gray-800 rounded-lg p-4">
              <SectionTitle>ショット遷移マトリクス</SectionTitle>
              <TransitionMatrix playerId={selectedPlayerId!} />
            </div>
            </ErrorBoundary>
          )}
        </div>
      )}
    </div>
  )
}
