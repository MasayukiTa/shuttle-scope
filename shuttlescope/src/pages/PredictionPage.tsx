/**
 * PredictionPage — 予測タブのトップレベルページ
 *
 * 選手選択 → PredictionPanel（試合プレビュー予測）
 *          → PairSimulationPanel（ペアシミュレーション）
 *
 * player / coach 向けロール制限あり
 */
import { useState, useEffect } from 'react'
import { analyticsViewLifecycle, trackAnalysisInteraction } from '@/utils/analytics'
import { AdviceStrip } from '@/components/common/AdviceStrip'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { apiGet, API_BASE_URL } from '@/api/client'
import { PredictionPanel } from '@/components/analysis/PredictionPanel'
import { PairSimulationPanel } from '@/components/analysis/PairSimulationPanel'
import { LineupOptimizerPanel } from '@/components/analysis/LineupOptimizerPanel'
import { HumanForecastPanel } from '@/components/analysis/HumanForecastPanel'
import { PrematchStatCard } from '@/components/analysis/PrematchStatCard'
import { useAuth } from '@/hooks/useAuth'
import { useCardTheme } from '@/hooks/useCardTheme'
import { useBreakpoint } from '@/hooks/useBreakpoint'
import { _RoleGuard } from '@/components/common/RoleGuard'
import { SearchableSelect } from '@/components/common/SearchableSelect'
import { MIcon } from '@/components/common/MIcon'

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
  // テレメトリ: page 滞在 dwell 計測 (view_id ベース)
  useEffect(() => analyticsViewLifecycle('prediction.page'), [])
  useCardTheme()
  // Precision on Gray: トークンベースのクラスに統一（useCardTheme のハードコード gray は使わない）
  const card = 'bg-[var(--ss-surface-1)] border border-[var(--ss-border)] shadow-card'
  const textHeading = 'text-[var(--ss-t1)]'
  const textSecondary = 'text-[var(--ss-t2)]'
  const textMuted = 'text-[var(--ss-t3)]'
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
  const forecastMatches = matchesResp?.data ?? []

  const { data: playersResp, isLoading: loadingPlayers } = useQuery({
    queryKey: ['players-list'],
    queryFn: () => apiGet<{ data: PlayerSummary[] }>('/players'),
  })
  const players: PlayerSummary[] = playersResp?.data ?? []
  const sortedPlayers = [...players].sort((a, b) => {
    if (a.is_target !== b.is_target) return a.is_target ? -1 : 1
    return (b.match_count ?? 0) - (a.match_count ?? 0)
  })
  const selectedPlayer = players.find((p) => p.id === selectedPlayerId)

  const headerBg = 'bg-[var(--ss-surface-1)] border-b border-[var(--ss-border)]'
  const bodyBg = 'bg-[var(--ss-bg-app)]'
  const { below: bpBelow } = useBreakpoint()
  const useShortLabel = bpBelow('md')  // md 未満 (=スマホ縦) では短縮ラベル
  const tabActive = 'bg-[var(--ss-surface-3)] text-[var(--ss-t1)]'
  const tabInactive = 'text-[var(--ss-t3)] hover:text-[var(--ss-t1)] hover:bg-[var(--ss-surface-2)]'

  const ROLE_LABELS: Record<string, string> = {
    admin: '管理者',
    analyst: 'アナリスト',
    coach: 'コーチ',
    player: '選手',
  }
  const ROLE_BADGE_CLASS: Record<string, string> = {
    admin: 'bg-[var(--ss-danger-bg)] border-[var(--ss-danger-border)] text-[var(--ss-danger-text)]',
    analyst: 'bg-[var(--ss-info-bg)] border-[var(--ss-info-border)] text-[var(--ss-info-text)]',
    coach: 'bg-[var(--ss-info-bg)] border-[var(--ss-info-border)] text-[var(--ss-info-text)]',
    player: 'bg-[var(--ss-surface-2)] border-[var(--ss-border)] text-[var(--ss-t2)]',
  }

  return (
      <div className={`flex flex-col h-full ${bodyBg} text-[var(--ss-t1)]`}>
        {/* ヘッダー */}
        <div className={`px-6 pt-6 pb-4 shrink-0 ${headerBg}`}>
          {/* タイトル行 */}
          <div className="flex items-center gap-3 mb-4">
            <MIcon name="trending_up" className="text-[var(--ss-brand)]" size={20} />
            <h1 className={`text-xl font-semibold tracking-[-0.014em] ${textHeading}`}>{t('nav.prediction_title')}</h1>
            {role && (
              <span
                className={`inline-flex items-center px-2 py-0.5 rounded-ss-sm border text-xs font-medium ${
                  ROLE_BADGE_CLASS[role] ?? 'bg-[var(--ss-surface-2)] border-[var(--ss-border)] text-[var(--ss-t2)]'
                }`}
              >
                {ROLE_LABELS[role] ?? role}
              </span>
            )}
          </div>

          {/* 選手セレクター行 */}
          <div className="flex items-center gap-3">
            <MIcon name="person" size={16} className={`${textMuted} shrink-0`} />
            <label className={`text-sm ${textSecondary} shrink-0`}>{t('auto.PredictionPage.k1')}</label>
            <SearchableSelect
              options={sortedPlayers.map((p) => ({
                value: p.id,
                label: p.name,
                searchText: p.team ?? '',
                prefix: p.is_target ? 'star' : undefined,
                prefixIsIcon: !!p.is_target,
                suffix: `${p.team ? `（${p.team}）` : ''} [${p.match_count ?? 0}試合]`,
              }))}
              value={selectedPlayerId}
              onChange={(v) => setSelectedPlayerId(v != null ? Number(v) : null)}
              emptyLabel={t('common.select_player', 'Select player')}
              placeholder={t('auto.PredictionPage.k5')}
              loading={loadingPlayers}
              className="min-w-[280px]"
            />
          </div>

          {/* 4. Prediction タブ: 実データ起点の advice strip (head-to-head 実績 or 過去 90 日サマリ) */}
          {selectedPlayerId && (
            <div className="mt-3">
              <AdviceStrip
                context="prediction.tab"
                playerId={selectedPlayerId}
                opponentId={opponentId || undefined}
              />
            </div>
          )}

          {/* 相手・大会レベルセレクター行（preview サブタブ + 選手選択済み時のみ） */}
          {selectedPlayerId && subTab === 'preview' && (
            <div className="flex items-center gap-4 mt-3 flex-wrap">
              <div className="flex items-center gap-2">
                <MIcon name="swords" size={15} className={`${textMuted} shrink-0`} />
                <label className={`text-sm ${textSecondary} shrink-0`}>{t('auto.PredictionPage.k2')}</label>
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
                  placeholder={t('auto.PredictionPage.k6')}
                  className="min-w-[240px]"
                />
              </div>
              <div className="flex items-center gap-2">
                <label className={`text-sm ${textSecondary} shrink-0`}>{t('auto.PredictionPage.k3')}</label>
                <select
                  value={tournamentLevel}
                  onChange={(e) => setTournamentLevel(e.target.value)}
                  className="text-base rounded-ss-md px-2 py-1.5 bg-[var(--ss-surface-1)] border border-[var(--ss-border-strong)] text-[var(--ss-t1)] focus:outline-none focus:border-[var(--ss-brand)] focus:ring-[3px] focus:ring-[var(--ss-focus-ring)] transition-colors duration-fast ease-out"
                >
                  <option value="">{t('auto.PredictionPage.k4')}</option>
                  {LEVEL_OPTIONS.map((lv) => {
                    const map: Record<string, [string, string]> = {
                      '全日本': ['tournament.national', '全日本'],
                      '国内':   ['tournament.domestic', '国内'],
                      'その他': ['tournament.other',    'その他'],
                    }
                    const hit = map[lv]
                    return <option key={lv} value={lv}>{hit ? t(hit[0], hit[1]) : lv}</option>
                  })}
                </select>
              </div>
            </div>
          )}
        </div>

        {/* サブタブ — 常に表示してレイアウトシフトを防ぐ */}
        <div className={`flex gap-1 px-6 py-2 border-b shrink-0 overflow-x-auto scrollbar-hide border-[var(--ss-border)] bg-[var(--ss-surface-1)] ${!selectedPlayerId ? 'invisible' : ''}`}>
          {(
            [
              { key: 'preview' as const, label: t('prediction.title'), labelShort: t('prediction.title_short') },
              { key: 'pair' as const, label: t('prediction.pair_simulation'), labelShort: t('prediction.pair_simulation_short') },
              { key: 'lineup' as const, label: t('prediction.lineup_optimizer'), labelShort: t('prediction.lineup_optimizer_short') },
              { key: 'forecast' as const, label: t('prediction.human_forecast'), labelShort: t('prediction.human_forecast_short') },
            ] as const
          ).map(({ key, label, labelShort }) => (
            <button
              key={key}
              onClick={() => {
                setSubTab(key)
                trackAnalysisInteraction('prediction.page', 'subtab_change', key)
              }}
              disabled={!selectedPlayerId}
              className={`px-3 py-1 rounded-ss-md text-sm font-medium transition-colors duration-base ease-out whitespace-nowrap ${
                subTab === key ? tabActive : tabInactive
              }`}
            >
              {useShortLabel ? labelShort : label}
            </button>
          ))}
        </div>

        {/* ダウンロードボタン */}
        {selectedPlayerId && (
          <div className="flex items-center justify-end gap-1.5 px-6 py-2 border-b shrink-0 border-[var(--ss-border)] bg-[var(--ss-surface-1)]">
            <MIcon name="file_download" size={13} className={textMuted} />
            <button
              onClick={() => dlReport(`/api/reports/prediction_pdf?player_id=${selectedPlayerId}`, `prediction_${selectedPlayerId}.pdf`)}
              className="text-xs px-2.5 py-1 rounded-ss-md border transition-colors duration-base ease-out border-[var(--ss-border-strong)] text-[var(--ss-t2)] hover:bg-[var(--ss-surface-2)]"
            >
              {t('auto.PredictionPage.pdf')}
            </button>
            <button
              onClick={() => dlReport(`/api/reports/prediction?player_id=${selectedPlayerId}`, `prediction_${selectedPlayerId}.json`)}
              className="text-xs px-2.5 py-1 rounded-ss-md border transition-colors duration-base ease-out border-[var(--ss-border-strong)] text-[var(--ss-t2)] hover:bg-[var(--ss-surface-2)]"
            >
              {t('auto.PredictionPage.json')}
            </button>
          </div>
        )}

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
              <div className={`${card} rounded-ss-lg p-4`}>
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
              <div className={`${card} rounded-ss-lg p-4`}>
                <p className={`text-xs font-semibold mb-2 ${textMuted}`}>
                  {t('auto.PredictionPage.select_match')}
                </p>
                <SearchableSelect
                  options={forecastMatches.map((m) => ({
                    value: m.id,
                    label: `${m.date} ${m.tournament_level ? `[${m.tournament_level}]` : ''}`,
                    suffix: m.result ? (m.result === 'win' ? 'W' : m.result === 'loss' ? 'L' : m.result) : '未確定',
                    searchText: `${m.date} ${m.tournament_level ?? ''}`,
                  }))}
                  value={forecastMatchId}
                  onChange={(v) => setForecastMatchId(v != null ? Number(v) : null)}
                  emptyLabel={t('common.select_match', 'Select match')}
                  placeholder={t('auto.PredictionPage.k7')}
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
                <div className={`${card} rounded-ss-lg p-4`}>
                  <HumanForecastPanel matchId={forecastMatchId} playerId={selectedPlayerId} />
                </div>
              )}
            </div>
          )}
        </div>
      </div>
  )
}
