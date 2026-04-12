/**
 * LineupOptimizerPanel — Phase S3: 複数候補選手をランク付けして推奨選手を提示
 *
 * analyst / coach 向け。
 * - 候補選手チェックボックス（2名以上選択で有効）
 * - 対戦相手・大会レベルフィルター（任意）
 * - 実行 → 勝率降順ランキング + 推奨バッジ
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Trophy } from 'lucide-react'
import { apiGet } from '@/api/client'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { WIN, LOSS } from '@/styles/colors'

// ── 型定義 ──────────────────────────────────────────────────────────────────

interface PlayerSummary {
  id: number
  name: string
  team?: string
  match_count?: number
}

interface RankedPlayer {
  rank: number
  player_id: number
  player_name: string
  win_probability: number
  sample_size: number
  h2h_available: boolean
  level_matches_available: boolean
}

interface LineupResult {
  ranked_players: RankedPlayer[]
  opponent_id: number | null
  tournament_level: string | null
  recommendation: string | null
}

interface Props {
  players: PlayerSummary[]
}

const LEVEL_OPTIONS = ['', 'IC', 'IS', 'SJL', '全日本', '国内', 'その他']

// ── メインコンポーネント ──────────────────────────────────────────────────────

export function LineupOptimizerPanel({ players }: Props) {
  const { t } = useTranslation()
  const isLight = useIsLightMode()
  const neutral = isLight ? '#334155' : '#d1d5db'
  const subText = isLight ? '#64748b' : '#9ca3af'
  const inputClass = `text-sm rounded px-2 py-1.5 focus:outline-none ${
    isLight
      ? 'bg-white border border-gray-300 text-gray-800'
      : 'bg-gray-700 border border-gray-600 text-gray-200'
  }`

  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [opponentId, setOpponentId] = useState<number | null>(null)
  const [level, setLevel] = useState('')
  const [enabled, setEnabled] = useState(false)

  const canRun = selectedIds.size >= 2

  const { data: resp, isLoading, isFetching } = useQuery({
    queryKey: ['lineup-optimizer', Array.from(selectedIds).sort().join(','), opponentId, level],
    queryFn: () =>
      apiGet<{ success: boolean; data: LineupResult }>('/prediction/lineup_optimizer', {
        player_ids: Array.from(selectedIds).join(','),
        ...(opponentId ? { opponent_id: opponentId } : {}),
        ...(level ? { tournament_level: level } : {}),
      }),
    enabled,
  })

  const result = resp?.data

  function togglePlayer(id: number) {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
    setEnabled(false)
  }

  function handleRun() {
    if (!canRun) return
    setEnabled(true)
  }

  return (
    <div className="space-y-4">
      {/* 候補選手チェックボックス */}
      <div>
        <p className="text-xs font-semibold mb-2" style={{ color: subText }}>
          {t('prediction.lineup_add_player')}（{selectedIds.size}名選択中）
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-1.5">
          {players.map((p) => (
            <label
              key={p.id}
              className={`flex items-center gap-2 text-xs px-2 py-1.5 rounded cursor-pointer transition-colors ${
                selectedIds.has(p.id)
                  ? isLight
                    ? 'bg-blue-50 border border-blue-300 text-blue-800'
                    : 'bg-blue-900/30 border border-blue-600 text-blue-300'
                  : isLight
                  ? 'bg-white border border-gray-200 text-gray-700 hover:bg-gray-50'
                  : 'bg-gray-700 border border-gray-600 text-gray-300 hover:bg-gray-600'
              }`}
            >
              <input
                type="checkbox"
                checked={selectedIds.has(p.id)}
                onChange={() => togglePlayer(p.id)}
                className="accent-blue-500"
              />
              <div className="min-w-0">
                <div className="truncate font-medium">{p.name}</div>
                {p.team && <div className="truncate opacity-60">{p.team}</div>}
              </div>
            </label>
          ))}
        </div>
      </div>

      {/* フィルター */}
      <div className="flex gap-2 flex-wrap">
        <select
          value={opponentId ?? ''}
          onChange={(e) => { setOpponentId(e.target.value ? Number(e.target.value) : null); setEnabled(false) }}
          className={inputClass}
        >
          <option value="">{t('prediction.lineup_vs_opponent')}（任意）</option>
          {players.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
        <select
          value={level}
          onChange={(e) => { setLevel(e.target.value); setEnabled(false) }}
          className={inputClass}
        >
          <option value="">{t('prediction.select_level')}</option>
          {LEVEL_OPTIONS.filter(Boolean).map((lv) => (
            <option key={lv} value={lv}>{lv}</option>
          ))}
        </select>
      </div>

      {/* 実行ボタン */}
      <button
        onClick={handleRun}
        disabled={!canRun || isLoading || isFetching}
        className="w-full py-2 rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-sm font-medium text-white transition-colors"
      >
        {isLoading || isFetching ? '計算中...' : t('prediction.lineup_run')}
      </button>
      {!canRun && (
        <p className="text-[11px]" style={{ color: subText }}>
          2名以上の選手を選択してください
        </p>
      )}

      {/* 結果 */}
      {result && result.ranked_players.length > 0 && (
        <div className="space-y-3">
          {/* 推奨バッジ */}
          {result.recommendation && (
            <div
              className="flex items-center gap-2 px-3 py-2 rounded"
              style={{
                background: isLight ? '#f0fdf4' : '#14532d33',
                border: `1px solid ${WIN}40`,
              }}
            >
              <Trophy size={14} style={{ color: WIN }} />
              <span className="text-sm font-semibold" style={{ color: WIN }}>
                {t('prediction.lineup_recommendation')}: {result.recommendation}
              </span>
            </div>
          )}

          {/* ランキングリスト */}
          <div className="space-y-1.5">
            {result.ranked_players.map((rp) => {
              const pct = Math.round(rp.win_probability * 100)
              const isTop = rp.rank === 1
              return (
                <div
                  key={rp.player_id}
                  className="flex items-center gap-3 px-3 py-2 rounded"
                  style={{
                    background: isLight ? '#f8fafc' : '#1e293b',
                    border: isTop ? `1px solid ${WIN}60` : `1px solid transparent`,
                  }}
                >
                  {/* ランク */}
                  <span
                    className="text-xs font-bold w-5 text-center shrink-0"
                    style={{ color: isTop ? WIN : subText }}
                  >
                    {rp.rank}
                  </span>

                  {/* 選手名 */}
                  <span className="flex-1 text-sm font-medium truncate" style={{ color: neutral }}>
                    {rp.player_name}
                  </span>

                  {/* H2H バッジ */}
                  {rp.h2h_available && (
                    <span
                      className="text-[10px] px-1 rounded shrink-0"
                      style={{
                        color: isLight ? '#1d4ed8' : '#93c5fd',
                        background: isLight ? '#dbeafe' : '#1d4ed820',
                      }}
                    >
                      H2H
                    </span>
                  )}

                  {/* サンプル数 */}
                  <span className="text-[11px] shrink-0" style={{ color: subText }}>
                    {rp.sample_size}試合
                  </span>

                  {/* 勝率バー */}
                  <div className="flex items-center gap-1.5 shrink-0">
                    <div className="w-16 h-1.5 bg-gray-700 rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all"
                        style={{
                          width: `${pct}%`,
                          background: pct >= 55 ? WIN : pct <= 45 ? LOSS : '#d97706',
                        }}
                      />
                    </div>
                    <span
                      className="text-sm font-bold w-10 text-right shrink-0"
                      style={{ color: pct >= 55 ? WIN : pct <= 45 ? LOSS : neutral }}
                    >
                      {pct}%
                    </span>
                  </div>
                </div>
              )
            })}
          </div>

          {/* 注釈 */}
          <p className="text-[10px]" style={{ color: subText }}>
            ※ 勝率はキャリブレーション済み多特徴量モデルによる予測値です
          </p>
        </div>
      )}
    </div>
  )
}
