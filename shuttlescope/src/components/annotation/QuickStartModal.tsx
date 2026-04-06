/**
 * クイックスタートモーダル（V4）
 * 相手選手情報が不完全な状態でも即座に試合を開始できる。
 * 未登録相手は暫定（provisional）として自動作成する。
 */
import { useState, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { Zap, X, Search, UserPlus, User, ChevronDown } from 'lucide-react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { apiGet, apiPost } from '@/api/client'
import { Player, MATCH_ROUNDS } from '@/types'

interface Props {
  onClose: () => void
  onStarted: (matchId: number) => void
}

const COMPETITION_TYPES = [
  { value: 'official', label: '公式戦' },
  { value: 'practice_match', label: '練習試合' },
  { value: 'open_practice', label: '公開練習' },
  { value: 'unknown', label: '不明' },
] as const

export function QuickStartModal({ onClose, onStarted }: Props) {
  const { t } = useTranslation()

  // 自チーム選手
  const [playerAId, setPlayerAId] = useState<number | ''>('')
  // 相手選手
  const [opponentQuery, setOpponentQuery] = useState('')
  const [opponentId, setOpponentId] = useState<number | null>(null)
  const [opponentName, setOpponentName] = useState('')
  const [showCandidates, setShowCandidates] = useState(false)
  // 試合設定
  const [initialServer, setInitialServer] = useState<'player_a' | 'player_b' | ''>('')
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

  // クイックスタートミューテーション
  const quickStart = useMutation({
    mutationFn: (body: object) => apiPost('/matches/quick-start', body),
    onSuccess: (data: any) => {
      const matchId = data?.data?.match?.id
      if (matchId) {
        onStarted(matchId)
      }
    },
  })

  // 相手選手の入力が変わったら選択をリセット
  useEffect(() => {
    if (opponentId !== null) {
      setOpponentId(null)
      setOpponentName('')
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
            <Zap size={18} className="text-yellow-400" />
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
            <select
              value={playerAId}
              onChange={(e) => setPlayerAId(e.target.value ? Number(e.target.value) : '')}
              className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm"
            >
              <option value="">{t('quick_start.select_player')}</option>
              {(targetPlayers.length > 0 ? targetPlayers : allPlayers).map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
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
                        <span className="flex items-center gap-2">
                          <User size={12} className="text-gray-400 shrink-0" />
                          <span>{p.name}</span>
                          {p.needs_review && (
                            <span className="text-xs text-yellow-400 bg-yellow-400/10 px-1 rounded">暫定</span>
                          )}
                        </span>
                        {p.match_count ? (
                          <span className="text-xs text-gray-400">{p.match_count}試合</span>
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
                        <span>「{opponentQuery.trim()}」を暫定登録して開始</span>
                      </button>
                    )}
                  </>
                )}
              </div>
            )}
          </div>

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
              className="flex-1 py-2 bg-yellow-500 hover:bg-yellow-400 text-gray-900 font-semibold rounded text-sm flex items-center justify-center gap-2 disabled:opacity-40"
            >
              <Zap size={15} />
              {quickStart.isPending ? t('quick_start.starting') : t('quick_start.start_now')}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
