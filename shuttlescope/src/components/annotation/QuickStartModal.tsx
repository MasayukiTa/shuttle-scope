/**
 * クイックスタートモーダル（V4）
 * 相手選手情報が不完全な状態でも即座に試合を開始できる。
 * 未登録相手は暫定（provisional）として自動作成する。
 */
import { useState, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { X, Search, UserPlus, User, ChevronDown } from 'lucide-react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { apiGet, apiPost } from '@/api/client'
import { Player, MATCH_ROUNDS } from '@/types'
import { SearchableSelect } from '@/components/common/SearchableSelect'

interface Props {
  onClose: () => void
  onStarted: (matchId: number) => void
}

export function QuickStartModal({ onClose, onStarted }: Props) {
  const { t } = useTranslation()

  const COMPETITION_TYPES = [
    { value: 'official', label: t('quick_start.competition_official') },
    { value: 'practice_match', label: t('quick_start.competition_practice_match') },
    { value: 'open_practice', label: t('quick_start.competition_open_practice') },
    { value: 'unknown', label: t('quick_start.competition_unknown') },
  ] as const

  // 自チーム選手
  const [playerAId, setPlayerAId] = useState<number | ''>('')
  // 相手選手
  const [opponentQuery, setOpponentQuery] = useState('')
  const [opponentId, setOpponentId] = useState<number | null>(null)
  const [opponentName, setOpponentName] = useState('')
  const [opponentTeam, setOpponentTeam] = useState('')
  const [showCandidates, setShowCandidates] = useState(false)
  // 試合設定
  const [initialServer, setInitialServer] = useState<'player_a' | 'player_b' | ''>('')
  // アナリスト視点: セット1開始時に自選手がいる側（top=画面上 / bottom=画面下）
  const [analystSide, setAnalystSide] = useState<'top' | 'bottom'>('bottom')
  const [competitionType, setCompetitionType] = useState<string>('unknown')
  const [tournament, setTournament] = useState('')
  const [round, setRound] = useState('')

  const searchRef = useRef<HTMLInputElement>(null)
  const candidatesRef = useRef<HTMLDivElement>(null)

  // 自チーム選手一覧
  const { data: playersData } = useQuery({
    queryKey: ['players'],
    queryFn: () => apiGet<{ success: boolean; data: Player[] }>('/players'),
  })
  const players = playersData?.data ?? []
  const targetPlayers = players.filter((p) => p.is_target)
  const allPlayers = players

  // 相手選手候補検索
  const { data: searchData, isFetching: isSearching } = useQuery({
    queryKey: ['players-search', opponentQuery],
    queryFn: () => apiGet<{ success: boolean; data: Player[] }>('/players/search', { q: opponentQuery }),
    enabled: opponentQuery.trim().length >= 1 && opponentId === null,
  })
  const candidates = searchData?.data ?? []

  // チーム候補 = 現在の名前検索結果から抽出（名前に紐づくチームのみ提示）
  const teamSuggestions = [...new Set(candidates.map((p) => p.team).filter(Boolean) as string[])]

  // クイックスタートミューテーション
  const quickStart = useMutation({
    mutationFn: (body: object) => apiPost('/matches/quick-start', body),
    onSuccess: (data: any) => {
      const matchId = data?.data?.match?.id
      if (matchId) {
        // アナリスト視点をlocalStorageに保存（AnnotatorPageで読み込む）
        localStorage.setItem(`shuttlescope.viewpoint.${matchId}`, analystSide)
        onStarted(matchId)
      }
    },
  })

  // 相手選手の入力が変わったら選択をリセット
  useEffect(() => {
    if (opponentId !== null) {
      setOpponentId(null)
      setOpponentName('')
      setOpponentTeam('')
    }
    setShowCandidates(opponentQuery.trim().length >= 1)
  }, [opponentQuery]) // eslint-disable-line react-hooks/exhaustive-deps

  // 外部クリックで候補を閉じる
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (
        candidatesRef.current &&
        !candidatesRef.current.contains(e.target as Node) &&
        searchRef.current &&
        !searchRef.current.contains(e.target as Node)
      ) {
        setShowCandidates(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const selectCandidate = (p: Player) => {
    setOpponentId(p.id)
    setOpponentName(p.name)
    setOpponentQuery(p.name)
    // 既存選手のチームを自動セット（確認・修正可能）
    setOpponentTeam(p.team ?? '')
    setShowCandidates(false)
  }

  const useNewOpponent = () => {
    setOpponentId(null)
    setOpponentName(opponentQuery.trim())
    setShowCandidates(false)
  }

  const canStart =
    playerAId !== '' &&
    (opponentId !== null || opponentQuery.trim().length >= 1)

  const handleStart = () => {
    if (!canStart) return
    const resolvedName = opponentId !== null ? opponentName : opponentQuery.trim()
    quickStart.mutate({
      player_a_id: Number(playerAId),
      opponent_name: resolvedName,
      opponent_id: opponentId ?? undefined,
      opponent_team: opponentTeam.trim() || undefined,
      initial_server: initialServer || undefined,
      competition_type: competitionType,
      tournament: tournament.trim() || undefined,
      round: round || undefined,
      format: 'singles',
    })
  }

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="bg-gray-800 rounded-lg w-full max-w-lg">
        {/* ヘッダー */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-700">
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-semibold">{t('quick_start.title')}</h2>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-white">
            <X size={18} />
          </button>
        </div>

        <div className="p-6 flex flex-col gap-4">
          {/* 自チーム選手 */}
          <div>
            <label className="block text-sm text-gray-400 mb-1">
              {t('quick_start.my_player')} *
            </label>
            <SearchableSelect
              options={(targetPlayers.length > 0 ? targetPlayers : allPlayers).map((p) => ({
                value: p.id,
                label: p.name,
                searchText: p.team ?? '',
                prefix: p.is_target ? '★' : undefined,
                suffix: p.team ? t('quick_start.team_suffix', { team: p.team }) : undefined,
              }))}
              value={playerAId === '' ? null : playerAId}
              onChange={(v) => setPlayerAId(v != null ? Number(v) : '')}
              emptyLabel={t('quick_start.select_player')}
              placeholder={t('quick_start.player_search_placeholder')}
            />
          </div>

          {/* 対戦相手名（検索付き） */}
          <div className="relative">
            <label className="block text-sm text-gray-400 mb-1">
              {t('quick_start.opponent')} *
            </label>
            <div className="relative">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                ref={searchRef}
                value={opponentQuery}
                onChange={(e) => setOpponentQuery(e.target.value)}
                onFocus={() => opponentQuery.trim().length >= 1 && setShowCandidates(true)}
                placeholder={t('quick_start.opponent_placeholder')}
                className="w-full bg-gray-700 border border-gray-600 rounded pl-8 pr-3 py-2 text-sm"
                autoComplete="off"
              />
              {opponentId !== null && (
                <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
                  <User size={12} className="text-green-400" />
                  <span className="text-xs text-green-400">{t('quick_start.existing')}</span>
                </div>
              )}
            </div>

            {/* 候補ドロップダウン */}
            {showCandidates && (
              <div
                ref={candidatesRef}
                className="absolute z-10 top-full mt-1 w-full bg-gray-700 border border-gray-600 rounded shadow-lg max-h-48 overflow-y-auto"
              >
                {isSearching ? (
                  <div className="px-3 py-2 text-sm text-gray-400">{t('app.loading')}</div>
                ) : (
                  <>
                    {candidates.map((p) => (
                      <button
                        key={p.id}
                        onClick={() => selectCandidate(p)}
                        className="w-full text-left px-3 py-2 hover:bg-gray-600 text-sm flex items-center justify-between"
                      >
                        <span className="flex items-center gap-2 min-w-0">
                          <User size={12} className="text-gray-400 shrink-0" />
                          <span className="truncate">{p.name}</span>
                          {p.team && (
                            <span className="text-xs text-blue-300 bg-blue-900/30 px-1.5 rounded shrink-0">{p.team}</span>
                          )}
                          {p.needs_review && (
                            <span className="text-xs text-yellow-400 bg-yellow-400/10 px-1 rounded shrink-0">{t('quick_start.provisional')}</span>
                          )}
                        </span>
                        {p.match_count ? (
                          <span className="text-xs text-gray-400 shrink-0 ml-1">{t('quick_start.match_count', { count: p.match_count })}</span>
                        ) : null}
                      </button>
                    ))}
                    {/* 新規作成オプション */}
                    {opponentQuery.trim().length >= 1 && (
                      <button
                        onClick={useNewOpponent}
                        className="w-full text-left px-3 py-2 hover:bg-blue-700/30 text-sm flex items-center gap-2 text-blue-300 border-t border-gray-600"
                      >
                        <UserPlus size={12} className="shrink-0" />
                        <span>{t('quick_start.provisional_register_and_start', { name: opponentQuery.trim() })}</span>
                      </button>
                    )}
                  </>
                )}
              </div>
            )}
          </div>

          {/* チーム名（名前入力後に表示） */}
          {(opponentQuery.trim().length >= 1) && (
            <div>
              <label className="block text-sm text-gray-400 mb-1">
                {t('quick_start.opponent_team')}
                <span className="ml-1 text-gray-600 text-xs">{t('quick_start.opponent_team_hint')}</span>
              </label>
              <input
                list="opponent-teams-list"
                value={opponentTeam}
                onChange={(e) => setOpponentTeam(e.target.value)}
                placeholder={t('quick_start.opponent_team_placeholder')}
                className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm"
                autoComplete="off"
              />
              <datalist id="opponent-teams-list">
                {teamSuggestions.map((team) => (
                  <option key={team} value={team} />
                ))}
              </datalist>
              {opponentId !== null && opponentTeam && (
                <p className="text-[11px] text-blue-400 mt-0.5">{t('quick_start.existing_team_editable')}</p>
              )}
            </div>
          )}

          {/* 先サーブ */}
          <div>
            <label className="block text-sm text-gray-400 mb-1">
              {t('quick_start.initial_server')}
            </label>
            <div className="flex gap-2">
              {[
                { value: 'player_a', label: t('quick_start.my_side') },
                { value: 'player_b', label: t('quick_start.opponent_side') },
              ].map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setInitialServer(opt.value as 'player_a' | 'player_b')}
                  className={`flex-1 py-1.5 rounded text-sm border ${
                    initialServer === opt.value
                      ? 'bg-blue-600 border-blue-500 text-white'
                      : 'bg-gray-700 border-gray-600 text-gray-300 hover:bg-gray-600'
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* アナリスト視点（コートのどちら側が自選手か） */}
          <div>
            <label className="block text-sm text-gray-400 mb-1">
              {t('quick_start.analyst_side_label')}
            </label>
            <div className="flex gap-2">
              {[
                { value: 'bottom' as const, label: t('quick_start.analyst_side_bottom'), hint: t('quick_start.analyst_side_bottom_hint') },
                { value: 'top' as const, label: t('quick_start.analyst_side_top'), hint: '' },
              ].map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setAnalystSide(opt.value)}
                  className={`flex-1 py-1.5 rounded text-sm border text-left px-2 ${
                    analystSide === opt.value
                      ? 'bg-blue-600 border-blue-500 text-white'
                      : 'bg-gray-700 border-gray-600 text-gray-300 hover:bg-gray-600'
                  }`}
                >
                  <span className="block text-xs font-medium">{opt.label}</span>
                  {opt.hint && <span className="block text-[10px] opacity-60">{opt.hint}</span>}
                </button>
              ))}
            </div>
          </div>

          {/* 大会区分 */}
          <div>
            <label className="block text-sm text-gray-400 mb-1">
              {t('quick_start.competition_type')}
            </label>
            <select
              value={competitionType}
              onChange={(e) => setCompetitionType(e.target.value)}
              className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm"
            >
              {COMPETITION_TYPES.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>

          {/* 大会名（任意） */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm text-gray-400 mb-1">
                {t('quick_start.tournament_optional')}
              </label>
              <input
                value={tournament}
                onChange={(e) => setTournament(e.target.value)}
                placeholder={t('quick_start.tournament_placeholder')}
                className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1 flex items-center gap-1">
                {t('quick_start.round_optional')}
              </label>
              <div className="relative">
                <select
                  value={round}
                  onChange={(e) => setRound(e.target.value)}
                  className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm appearance-none"
                >
                  <option value="">{t('quick_start.round_blank')}</option>
                  {MATCH_ROUNDS.map((r) => (
                    <option key={r} value={r}>{r}</option>
                  ))}
                </select>
                <ChevronDown size={12} className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
              </div>
            </div>
          </div>

          {/* エラー表示 */}
          {quickStart.isError && (
            <div className="text-sm text-red-400 bg-red-400/10 rounded px-3 py-2">
              {t('quick_start.error')}
            </div>
          )}

          {/* ボタン */}
          <div className="flex gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 py-2 bg-gray-700 hover:bg-gray-600 rounded text-sm"
            >
              {t('app.cancel')}
            </button>
            <button
              type="button"
              onClick={handleStart}
              disabled={!canStart || quickStart.isPending}
              className="flex-1 py-2 bg-yellow-600 hover:bg-yellow-500 text-white font-semibold rounded text-sm flex items-center justify-center gap-2 disabled:opacity-40"
            >
              {quickStart.isPending ? t('quick_start.starting') : t('quick_start.start_now')}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
