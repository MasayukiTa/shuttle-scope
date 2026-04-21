/**
 * PredictionPage — 予測タブのトップレベルページ
 *
 * 選手選択 → PredictionPanel（試合プレビュー予測）
 *          → PairSimulationPanel（ペアシミュレーション）
 *
 * player / coach 向けロール制限あり
 */
import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { User, TrendingUp, Swords } from 'lucide-react'
import { apiGet } from '@/api/client'
import { PredictionPanel } from '@/components/analysis/PredictionPanel'
import { PairSimulationPanel } from '@/components/analysis/PairSimulationPanel'
import { LineupOptimizerPanel } from '@/components/analysis/LineupOptimizerPanel'
import { HumanForecastPanel } from '@/components/analysis/HumanForecastPanel'
import { PrematchStatCard } from '@/components/analysis/PrematchStatCard'
import { useAuth } from '@/hooks/useAuth'
import { useCardTheme } from '@/hooks/useCardTheme'
import { RoleGuard } from '@/components/common/RoleGuard'
import { SearchableSelect } from '@/components/common/SearchableSelect'

interface PlayerSummary {
  id: number
  name: string
  team?: string
  is_target?: boolean
  match_count?: number
}

type SubTab = 'preview' | 'pair' | 'lineup' | 'forecast'

export function PredictionPage() {
  const { t } = useTranslation()
  const { role } = useAuth()
  const { card, textHeading, textSecondary, textMuted, isLight } = useCardTheme()
  const [searchParams] = useSearchParams()
  const [selectedPlayerId, setSelectedPlayerId] = useState<number | null>(() => {
    const pid = searchParams.get('playerId')
    return pid ? Number(pid) : null
  })
  const [subTab, setSubTab] = useState<SubTab>('preview')
  const [forecastMatchId, setForecastMatchId] = useState<number | null>(null)
  // preview サブタブ用: Page レベルで管理（PredictionPanel へ prop として渡す）
  const [opponentId, setOpponentId] = useState<number | null>(null)
  const [tournamentLevel, setTournamentLevel] = useState<string>('')

  const LEVEL_OPTIONS = ['IC', 'IS', 'SJL', '全日本', '国内', 'その他']

  // URL パラメータ変化に追従
  useEffect(() => {
    const pid = searchParams.get('playerId')
    if (pid) setSelectedPlayerId(Number(pid))
  }, [searchParams])

  const { data: matchesResp } = useQuery({
    queryKey: ['matches-for-forecast', selectedPlayerId],
    queryFn: () =>
      apiGet<{ data: Array<{ id: number; date: string; tournament_level?: string; result?: string }> }>(
        '/matches',
        { player_id: selectedPlayerId }
      ),
    enabled: !!selectedPlayerId && subTab === 'forecast',
  })
  const forecastMatches = (matchesResp as any)?.data ?? []

  const { data: playersResp, isLoading: loadingPlayers } = useQuery({
    queryKey: ['players-list'],
    queryFn: () => apiGet<{ data: PlayerSummary[] }>('/players'),
  })
  const players: PlayerSummary[] = (playersResp as any)?.data ?? []
  const sortedPlayers = [...players].sort((a, b) => {
    if (a.is_target !== b.is_target) return a.is_target ? -1 : 1
    return (b.match_count ?? 0) - (a.match_count ?? 0)
  })
  const selectedPlayer = players.find((p) => p.id === selectedPlayerId)

  const headerBg = isLight ? 'bg-white border-b border-gray-200' : 'bg-gray-900 border-b border-gray-700'
  const bodyBg = isLight ? 'bg-gray-50' : 'bg-gray-900'
  const tabActive = isLight ? 'bg-gray-200 text-gray-900' : 'bg-gray-700 text-white'
  const tabInactive = isLight
    ? 'text-gray-500 hover:text-gray-700 hover:bg-gray-100'
    : 'text-gray-400 hover:text-white hover:bg-gray-700'

  const ROLE_LABELS: Record<string, string> = {
    admin: '管理者',
    analyst: 'アナリスト',
    coach: 'コーチ',
    player: '選手',
  }
  const ROLE_BADGE_CLASS: Record<string, string> = {
    admin: 'bg-red-900/50 border-red-500 text-red-300',
    analyst: 'bg-blue-900/50 border-blue-500 text-blue-300',
    coach: 'bg-emerald-900/50 border-emerald-500 text-emerald-300',
    player: 'bg-purple-900/50 border-purple-500 text-purple-300',
  }

  return (
      <div className={`flex flex-col h-full ${bodyBg} ${isLight ? 'text-gray-900' : 'text-white'}`}>
        {/* ヘッダー */}
        <div className={`px-6 pt-6 pb-4 shrink-0 ${headerBg}`}>
          {/* タイトル行 */}
          <div className="flex items-center gap-3 mb-4">
            <TrendingUp className="text-blue-400" size={20} />
            <h1 className={`text-xl font-semibold ${textHeading}`}>{t('nav.prediction_title')}</h1>
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

          {/* 選手セレクター行 */}
          <div className="flex items-center gap-3">
            <User size={16} className={`${textMuted} shrink-0`} />
            <label className={`text-sm ${textSecondary} shrink-0`}>選手：</label>
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

          {/* 相手・大会レベルセレクター行（preview サブタブ + 選手選択済み時のみ） */}
          {selectedPlayerId && subTab === 'preview' && (
            <div className="flex items-center gap-4 mt-3 flex-wrap">
              <div className="flex items-center gap-2">
                <Swords size={15} className={`${textMuted} shrink-0`} />
                <label className={`text-sm ${textSecondary} shrink-0`}>相手：</label>
                <SearchableSelect
                  options={sortedPlayers
                    .filter((p) => p.id !== selectedPlayerId)
                    .map((p) => ({
                      value: p.id,
                      label: p.name,
                      searchText: p.team ?? '',
                      suffix: p.team ? `（${p.team}）` : undefined,
                    }))}
                  value={opponentId}
                  onChange={(v) => setOpponentId(v != null ? Number(v) : null)}
                  emptyLabel="— 相手を選択 —"
                  placeholder="相手選手名で検索..."
                  className="min-w-[240px]"
                />
              </div>
              <div className="flex items-center gap-2">
                <label className={`text-sm ${textSecondary} shrink-0`}>大会レベル：</label>
                <select
                  value={tournamentLevel}
                  onChange={(e) => setTournamentLevel(e.target.value)}
                  className={`text-sm rounded px-2 py-1.5 focus:outline-none ${
                    isLight
                      ? 'bg-white border border-gray-300 text-gray-800'
                      : 'bg-gray-700 border border-gray-600 text-gray-200'
                  }`}
                >
                  <option value="">— 全レベル —</option>
                  {LEVEL_OPTIONS.map((lv) => (
                    <option key={lv} value={lv}>{lv}</option>
                  ))}
                </select>
              </div>
            </div>
          )}
        </div>

        {/* サブタブ — 常に表示してレイアウトシフトを防ぐ */}
        <div className={`flex gap-1 px-6 py-2 border-b shrink-0 overflow-x-auto ${isLight ? 'border-gray-200 bg-white' : 'border-gray-800 bg-gray-900'} ${!selectedPlayerId ? 'invisible' : ''}`}>
          {(
            [
              { key: 'preview' as const, label: t('prediction.title') },
              { key: 'pair' as const, label: t('prediction.pair_simulation') },
              { key: 'lineup' as const, label: t('prediction.lineup_optimizer') },
              { key: 'forecast' as const, label: t('prediction.human_forecast') },
            ] as const
          ).map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setSubTab(key)}
              disabled={!selectedPlayerId}
              className={`px-3 py-1 rounded text-sm font-medium transition-colors whitespace-nowrap ${
                subTab === key ? tabActive : tabInactive
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {/* コンテンツ */}
        <div className="flex-1 overflow-y-auto px-6 py-5">
          {!selectedPlayerId ? (
            <div className={`flex items-center justify-center h-full ${textMuted} text-sm`}>
              {t('prediction.select_player')}
            </div>
          ) : subTab === 'preview' ? (
            <div className="grid grid-cols-1 xl:grid-cols-[3fr_2fr] gap-6 items-start">
              <div>
                <PredictionPanel
                  playerId={selectedPlayerId}
                  playerName={selectedPlayer?.name ?? ''}
                  players={sortedPlayers}
                  opponentId={opponentId}
                  tournamentLevel={tournamentLevel}
                />
              </div>
              {/* 右パネル（将来的に PrematchStatCard 等を配置） */}
              <div />
            </div>
          ) : subTab === 'pair' ? (
            <div>
              <PairSimulationPanel players={sortedPlayers} />
            </div>
          ) : subTab === 'lineup' ? (
            <div>
              <div className={`${card} rounded-lg p-4`}>
                <p className={`text-sm font-semibold mb-3 ${textHeading}`}>
                  {t('prediction.lineup_optimizer')}
                </p>
                <LineupOptimizerPanel players={sortedPlayers} role={role} />
              </div>
            </div>
          ) : (
            /* forecast タブ: 試合選択 + HumanForecastPanel */
            <div className="space-y-4">
              {/* 試合セレクター */}
              <div className={`${card} rounded-lg p-4`}>
                <p className={`text-xs font-semibold mb-2 ${textMuted}`}>
                  試合を選択
                </p>
                <SearchableSelect
                  options={forecastMatches.map((m: any) => ({
                    value: m.id,
                    label: `${m.date} ${m.tournament_level ? `[${m.tournament_level}]` : ''}`,
                    suffix: m.result ? (m.result === 'win' ? 'W' : m.result === 'loss' ? 'L' : m.result) : '未確定',
                    searchText: `${m.date} ${m.tournament_level ?? ''}`,
                  }))}
                  value={forecastMatchId}
                  onChange={(v) => setForecastMatchId(v != null ? Number(v) : null)}
                  emptyLabel="— 試合を選択 —"
                  placeholder="日付・大会レベルで検索..."
                  loading={forecastMatches.length === 0 && !!selectedPlayerId}
                />
              </div>

              {/* 試合前統計予測 */}
              {forecastMatchId && (
                <PrematchStatCard
                  matchId={forecastMatchId}
                  playerId={selectedPlayerId}
                  playerName={selectedPlayer?.name ?? ''}
                />
              )}

              {/* 人間予測入力パネル */}
              {forecastMatchId && (
                <div className={`${card} rounded-lg p-4`}>
                  <HumanForecastPanel matchId={forecastMatchId} playerId={selectedPlayerId} />
                </div>
              )}
            </div>
          )}
        </div>
      </div>
  )
}
