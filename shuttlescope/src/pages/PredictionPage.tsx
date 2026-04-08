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
import { User, TrendingUp } from 'lucide-react'
import { apiGet } from '@/api/client'
import { PredictionPanel } from '@/components/analysis/PredictionPanel'
import { PairSimulationPanel } from '@/components/analysis/PairSimulationPanel'
import { LineupOptimizerPanel } from '@/components/analysis/LineupOptimizerPanel'
import { HumanForecastPanel } from '@/components/analysis/HumanForecastPanel'
import { useAuth } from '@/hooks/useAuth'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { RoleGuard } from '@/components/common/RoleGuard'

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
  const isLight = useIsLightMode()
  const [searchParams] = useSearchParams()
  const [selectedPlayerId, setSelectedPlayerId] = useState<number | null>(() => {
    const pid = searchParams.get('playerId')
    return pid ? Number(pid) : null
  })
  const [subTab, setSubTab] = useState<SubTab>('preview')
  const [forecastMatchId, setForecastMatchId] = useState<number | null>(null)

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

  const headerBg = isLight ? 'bg-white border-gray-200' : 'bg-gray-900 border-gray-700'
  const bodyBg = isLight ? 'bg-gray-50' : 'bg-gray-900'
  const tabActive = isLight ? 'bg-gray-200 text-gray-900' : 'bg-gray-700 text-white'
  const tabInactive = isLight
    ? 'text-gray-500 hover:text-gray-700 hover:bg-gray-100'
    : 'text-gray-400 hover:text-white hover:bg-gray-700'

  return (
    <RoleGuard allowedRoles={['analyst', 'coach']} fallback={
      <div className="flex items-center justify-center h-screen text-gray-500">
        予測機能はアナリスト・コーチのみ利用できます
      </div>
    }>
      <div className={`flex flex-col h-screen ${bodyBg}`}>
        {/* ヘッダー */}
        <div className={`px-6 pt-4 pb-3 border-b shrink-0 ${headerBg}`}>
          {/* タイトル行 */}
          <div className="flex items-center gap-2 mb-3">
            <TrendingUp size={18} className="text-gray-400" />
            <h1 className="text-lg font-semibold" style={{ color: isLight ? '#1e293b' : '#f1f5f9' }}>
              {t('nav.prediction_title')}
            </h1>
            {role && (
              <span className={`text-xs px-2 py-0.5 rounded ml-1 ${isLight ? 'bg-gray-100 border border-gray-300 text-gray-600' : 'bg-gray-700 border border-gray-600 text-gray-300'}`}>
                {role === 'coach' ? 'コーチ' : 'アナリスト'}
              </span>
            )}
          </div>

          {/* 選手セレクター行 */}
          <div className="flex items-center gap-3">
            <User size={16} className="text-gray-400 shrink-0" />
            <label className="text-sm text-gray-400 shrink-0">選手：</label>
            {loadingPlayers ? (
              <span className="text-gray-500 text-sm">読み込み中...</span>
            ) : (
              <select
                className={`text-sm rounded-md px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500 min-w-[260px] ${
                  isLight
                    ? 'bg-white border border-gray-300 text-gray-800'
                    : 'bg-gray-800 border border-gray-700 text-white'
                }`}
                value={selectedPlayerId ?? ''}
                onChange={(e) => setSelectedPlayerId(e.target.value ? Number(e.target.value) : null)}
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

        {/* サブタブ */}
        {selectedPlayerId && (
          <div className={`flex gap-1 px-6 py-2 border-b shrink-0 overflow-x-auto ${headerBg}`}>
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
                className={`px-3 py-1 rounded text-sm font-medium transition-colors whitespace-nowrap ${
                  subTab === key ? tabActive : tabInactive
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        )}

        {/* コンテンツ */}
        <div className="flex-1 overflow-y-auto px-6 py-5">
          {!selectedPlayerId ? (
            <div className="flex items-center justify-center h-full text-gray-500 text-sm">
              {t('prediction.select_player')}
            </div>
          ) : subTab === 'preview' ? (
            <div className="max-w-2xl mx-auto">
              <PredictionPanel
                playerId={selectedPlayerId}
                playerName={selectedPlayer?.name ?? ''}
                players={sortedPlayers}
              />
            </div>
          ) : subTab === 'pair' ? (
            <div className="max-w-2xl mx-auto">
              <PairSimulationPanel players={sortedPlayers} />
            </div>
          ) : subTab === 'lineup' ? (
            <div className="max-w-2xl mx-auto">
              <div className={`rounded-lg p-4 ${isLight ? 'bg-white border border-gray-200' : 'bg-gray-800'}`}>
                <p className="text-sm font-semibold mb-3" style={{ color: isLight ? '#1e293b' : '#d1d5db' }}>
                  {t('prediction.lineup_optimizer')}
                </p>
                <LineupOptimizerPanel players={sortedPlayers} />
              </div>
            </div>
          ) : (
            /* forecast タブ: 試合選択 + HumanForecastPanel */
            <div className="max-w-2xl mx-auto space-y-4">
              {/* 試合セレクター */}
              <div className={`rounded-lg p-4 ${isLight ? 'bg-white border border-gray-200' : 'bg-gray-800'}`}>
                <p className="text-xs font-semibold mb-2" style={{ color: isLight ? '#64748b' : '#9ca3af' }}>
                  試合を選択
                </p>
                <select
                  className={`text-sm rounded px-2 py-1.5 w-full focus:outline-none ${
                    isLight
                      ? 'bg-white border border-gray-300 text-gray-800'
                      : 'bg-gray-700 border border-gray-600 text-gray-200'
                  }`}
                  value={forecastMatchId ?? ''}
                  onChange={(e) => setForecastMatchId(e.target.value ? Number(e.target.value) : null)}
                >
                  <option value="">— 試合を選択 —</option>
                  {forecastMatches.map((m: any) => (
                    <option key={m.id} value={m.id}>
                      {m.date} {m.tournament_level ? `[${m.tournament_level}]` : ''} {m.result ? `(${m.result === 'win' ? 'W' : m.result === 'loss' ? 'L' : m.result})` : '(未確定)'}
                    </option>
                  ))}
                </select>
                {forecastMatches.length === 0 && (
                  <p className="text-xs mt-1" style={{ color: isLight ? '#64748b' : '#9ca3af' }}>
                    試合データを読み込み中...
                  </p>
                )}
              </div>

              {/* 予測パネル */}
              {forecastMatchId && (
                <div className={`rounded-lg p-4 ${isLight ? 'bg-white border border-gray-200' : 'bg-gray-800'}`}>
                  <HumanForecastPanel matchId={forecastMatchId} playerId={selectedPlayerId} />
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </RoleGuard>
  )
}
