/**
 * LineupOptimizerPanel — Phase S3: ラインナップ最適化
 *
 * ロール別に異なる表示を行う:
 * - analyst/admin: 勝率ランキング（データあり先順・詳細比較用）
 * - coach:   候補セット表示（順位なし・レンジ表示・意思決定を誘導しない）
 *            ガイドライン: coach_lineup_optimization_guidance.txt 参照
 */
import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { AlertCircle, Search, X, CheckSquare, Square } from 'lucide-react'
import { apiGet } from '@/api/client'
import { SearchableSelect } from '@/components/common/SearchableSelect'
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
  role: 'admin' | 'analyst' | 'coach' | 'player' | null
}

const LEVEL_OPTIONS = ['', 'IC', 'IS', 'SJL', '全日本', '国内', 'その他']

// ── コーチ向け候補セット表示 ─────────────────────────────────────────────────
// 順位なし・勝率レンジ・「意思決定の材料」として提示

const PLAN_LABELS = ['案A', '案B', '案C']

function CoachCandidateView({
  result,
  isLight,
}: {
  result: LineupResult
  isLight: boolean
}) {
  const { t } = useTranslation()

  const subText = isLight ? '#64748b' : '#9ca3af'
  const neutral = isLight ? '#334155' : '#d1d5db'

  // 上位 3 案のみ表示（順位付けしない = PLAN_LABELS）
  const candidates = result.ranked_players.slice(0, 3)
  if (candidates.length === 0) return null

  return (
    <div className="space-y-3">
      {/* 注釈バナー */}
      <div
        className="flex items-start gap-2 px-3 py-2 rounded"
        style={{
          background: isLight ? '#f0fdf4' : '#14532d22',
          border: `1px solid #16a34a40`,
        }}
      >
        <AlertCircle size={13} className="shrink-0 mt-0.5" style={{ color: '#16a34a' }} />
        <p className="text-[11px]" style={{ color: isLight ? '#15803d' : '#86efac' }}>
          候補生成（参考）— 自動決定ではありません。単独で起用を決めないでください。
        </p>
      </div>

      {/* 候補セット */}
      <div className="grid gap-2">
        {candidates.map((rp, idx) => {
          const pct = Math.round(rp.win_probability * 100)
          // 不確実性を加味したレンジ表示（少数サンプルほど広く）
          const margin = rp.sample_size < 5 ? 15 : rp.sample_size < 10 ? 10 : 7
          const lo = Math.max(0, pct - margin)
          const hi = Math.min(100, pct + margin)
          const stability =
            rp.sample_size >= 10 ? '安定' : rp.sample_size >= 5 ? '中' : '荒れやすい'
          const stabilityColor =
            rp.sample_size >= 10
              ? WIN
              : rp.sample_size >= 5
              ? '#d97706'
              : isLight
              ? '#64748b'
              : '#9ca3af'

          return (
            <div
              key={rp.player_id}
              className="px-3 py-2.5 rounded"
              style={{
                background: isLight ? '#f8fafc' : '#1e293b',
                border: `1px solid ${isLight ? '#e2e8f0' : '#334155'}`,
              }}
            >
              {/* プラン名 + 選手名 */}
              <div className="flex items-center gap-2 mb-1.5">
                <span
                  className="text-[10px] font-bold px-1.5 py-0.5 rounded shrink-0"
                  style={{
                    background: isLight ? '#dbeafe' : '#1d4ed820',
                    color: isLight ? '#1d4ed8' : '#93c5fd',
                  }}
                >
                  {PLAN_LABELS[idx]}
                </span>
                <span className="text-sm font-semibold truncate" style={{ color: neutral }}>
                  {rp.player_name}
                </span>
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
              </div>

              {/* 勝率レンジ + 安定性 + サンプル数 */}
              <div className="flex items-center gap-3 flex-wrap">
                <div className="flex items-center gap-1">
                  <span className="text-[10px]" style={{ color: subText }}>{t('auto.LineupOptimizerPanel.k1')}</span>
                  <span className="text-sm font-bold" style={{ color: neutral }}>
                    {lo}–{hi}%
                  </span>
                  {rp.sample_size < 10 && (
                    <span className="text-[10px]" style={{ color: subText }}>
                      （参考: データ不足）
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-1">
                  <span className="text-[10px]" style={{ color: subText }}>{t('auto.LineupOptimizerPanel.k2')}</span>
                  <span className="text-[10px] font-medium" style={{ color: stabilityColor }}>
                    {stability}
                  </span>
                </div>
                <span className="text-[10px]" style={{ color: subText }}>
                  {rp.sample_size}試合
                </span>
              </div>
            </div>
          )
        })}
      </div>

      <p className="text-[10px]" style={{ color: subText }}>
        ※ 候補は相手・条件に応じた参考情報です。最終的な起用判断はコーチの裁量で行ってください。
      </p>
    </div>
  )
}

// ── アナリスト向けランキング表示 ─────────────────────────────────────────────

function AnalystRankingView({
  result,
  isLight,
}: {
  result: LineupResult
  isLight: boolean
}) {
  const subText = isLight ? '#64748b' : '#9ca3af'
  const neutral = isLight ? '#334155' : '#d1d5db'

  // データあり（勝率順）→ データなし（名前順）
  const withData = result.ranked_players.filter((rp) => rp.sample_size > 0)
  const noData = result.ranked_players.filter((rp) => rp.sample_size === 0)
    .sort((a, b) => a.player_name.localeCompare(b.player_name, 'ja'))

  const renderRow = (rp: RankedPlayer, displayRank: number | null) => {
    const pct = Math.round(rp.win_probability * 100)
    const isTop = displayRank === 1
    return (
      <div
        key={rp.player_id}
        className="flex items-center gap-3 px-3 py-2 rounded"
        style={{
          background: isLight ? '#f8fafc' : '#1e293b',
          border: isTop ? `1px solid ${WIN}60` : `1px solid transparent`,
        }}
      >
        <span
          className="text-xs font-bold w-5 text-center shrink-0"
          style={{ color: isTop ? WIN : subText }}
        >
          {displayRank ?? '—'}
        </span>
        <span
          className="flex-1 min-w-0 text-sm font-medium truncate"
          style={{ color: displayRank ? neutral : subText }}
          title={rp.player_name}
        >
          {rp.player_name}
        </span>
        {/* xs: バッジ群を隠して名前領域を確保。sm+ で表示 */}
        {rp.h2h_available && (
          <span
            className="hidden sm:inline-flex text-[10px] px-1 rounded shrink-0"
            style={{
              color: isLight ? '#1d4ed8' : '#93c5fd',
              background: isLight ? '#dbeafe' : '#1d4ed820',
            }}
          >
            H2H
          </span>
        )}
        <span className="hidden sm:inline text-[11px] shrink-0 num-cell" style={{ color: subText }}>
          {rp.sample_size > 0 ? `${rp.sample_size}試合` : 'データなし'}
        </span>
        {rp.sample_size > 0 && (
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
              className="text-sm font-bold w-10 text-right shrink-0 num-cell"
              style={{ color: pct >= 55 ? WIN : pct <= 45 ? LOSS : neutral }}
            >
              {pct}%
            </span>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {/* ランキングリスト（データあり） */}
      <div className="space-y-1.5">
        {withData.map((rp, idx) => renderRow(rp, idx + 1))}
      </div>

      {/* データなし（末尾に別掲） */}
      {noData.length > 0 && (
        <details>
          <summary className="text-[11px] cursor-pointer select-none" style={{ color: subText }}>
            実績データなし — {noData.length}名（クリックで展開）
          </summary>
          <div className="mt-1 space-y-1">
            {noData.map((rp) => renderRow(rp, null))}
          </div>
        </details>
      )}

      <p className="text-[10px]" style={{ color: subText }}>
        ※ 勝率はキャリブレーション済み多特徴量モデルによる予測値です
      </p>
    </div>
  )
}

// ── メインコンポーネント ──────────────────────────────────────────────────────

export function LineupOptimizerPanel({ players, role }: Props) {
  const { t } = useTranslation()
  const isLight = useIsLightMode()
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
  const [nameFilter, setNameFilter] = useState('')
  const [teamFilter, setTeamFilter] = useState('')

  const isAnalyst = role === 'analyst' || role === 'admin'
  const canRun = selectedIds.size >= 2

  // チームリスト（重複除去・ソート）
  const teamOptions = useMemo(() => {
    const teams = Array.from(new Set(players.map((p) => p.team).filter(Boolean) as string[]))
    return teams.sort()
  }, [players])

  // 絞り込み後の選手リスト（選択済みは常に先頭）
  const filteredPlayers = useMemo(() => {
    const q = nameFilter.trim().toLowerCase()
    return players.filter((p) => {
      const matchName = !q || p.name.toLowerCase().includes(q)
      const matchTeam = !teamFilter || p.team === teamFilter
      return matchName && matchTeam
    })
  }, [players, nameFilter, teamFilter])

  // 絞り込み後のうち選択済み / 未選択
  const filteredSelectedIds = useMemo(
    () => filteredPlayers.filter((p) => selectedIds.has(p.id)).map((p) => p.id),
    [filteredPlayers, selectedIds]
  )
  const allFilteredSelected =
    filteredPlayers.length > 0 && filteredPlayers.every((p) => selectedIds.has(p.id))

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

  function toggleAllFiltered() {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (allFilteredSelected) {
        filteredPlayers.forEach((p) => next.delete(p.id))
      } else {
        filteredPlayers.forEach((p) => next.add(p.id))
      }
      return next
    })
    setEnabled(false)
  }

  function clearSelected() {
    setSelectedIds(new Set())
    setEnabled(false)
  }

  return (
    <div className="space-y-4">
      {/* ── 候補選手選択 ── */}
      <div className="space-y-2">
        {/* 見出し + 選択済みチップ */}
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <p className="text-xs font-semibold" style={{ color: subText }}>
            {t('prediction.lineup_add_player')}
            <span className="ml-1 font-normal">
              （{selectedIds.size}名選択中 / {players.length}名）
            </span>
          </p>
          {selectedIds.size > 0 && (
            <button
              onClick={clearSelected}
              className="text-[10px] flex items-center gap-0.5 hover:opacity-70 transition-opacity"
              style={{ color: subText }}
            >
              <X size={10} /> 選択クリア
            </button>
          )}
        </div>

        {/* 選択済み選手チップ（フィルターで隠れても常に表示） */}
        {selectedIds.size > 0 && (
          <div className="flex flex-wrap gap-1">
            {players
              .filter((p) => selectedIds.has(p.id))
              .map((p) => (
                <button
                  key={p.id}
                  onClick={() => togglePlayer(p.id)}
                  className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full transition-colors"
                  style={{
                    background: isLight ? '#dbeafe' : '#1d4ed830',
                    color: isLight ? '#1d4ed8' : '#93c5fd',
                    border: `1px solid ${isLight ? '#93c5fd' : '#1d4ed8'}`,
                  }}
                >
                  {p.name}
                  <X size={9} />
                </button>
              ))}
          </div>
        )}

        {/* 絞り込みバー */}
        <div className="flex gap-1.5 flex-wrap items-center">
          {/* 名前検索 */}
          <div
            className="flex items-center gap-1 flex-1 min-w-[140px] rounded px-2 py-1"
            style={{
              background: isLight ? '#f1f5f9' : '#374151',
              border: `1px solid ${isLight ? '#e2e8f0' : '#4b5563'}`,
            }}
          >
            <Search size={11} style={{ color: subText }} className="shrink-0" />
            <input
              type="text"
              value={nameFilter}
              onChange={(e) => setNameFilter(e.target.value)}
              placeholder={t('auto.LineupOptimizerPanel.k6')}
              className="flex-1 bg-transparent text-xs outline-none min-w-0"
              style={{ color: isLight ? '#1e293b' : '#e2e8f0' }}
            />
            {nameFilter && (
              <button onClick={() => setNameFilter('')}>
                <X size={10} style={{ color: subText }} />
              </button>
            )}
          </div>

          {/* チームフィルター */}
          {teamOptions.length > 0 && (
            <select
              value={teamFilter}
              onChange={(e) => setTeamFilter(e.target.value)}
              className="text-xs rounded px-2 py-1 focus:outline-none"
              style={{
                background: isLight ? '#f1f5f9' : '#374151',
                border: `1px solid ${isLight ? '#e2e8f0' : '#4b5563'}`,
                color: isLight ? '#1e293b' : '#e2e8f0',
              }}
            >
              <option value="">{t('auto.LineupOptimizerPanel.k3')}</option>
              {teamOptions.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          )}

          {/* 絞り込み全選択/解除 */}
          {filteredPlayers.length > 0 && (
            <button
              onClick={toggleAllFiltered}
              className="flex items-center gap-1 text-[10px] px-2 py-1 rounded transition-colors"
              style={{
                background: isLight ? '#f1f5f9' : '#374151',
                border: `1px solid ${isLight ? '#e2e8f0' : '#4b5563'}`,
                color: subText,
              }}
            >
              {allFilteredSelected
                ? <><CheckSquare size={11} /> {t('auto.LineupOptimizerPanel.k4')}</>
                : <><Square size={11} /> {t('auto.LineupOptimizerPanel.k5')}</>
              }
              {nameFilter || teamFilter ? '（絞り込み中）' : ''}
            </button>
          )}
        </div>

        {/* 件数表示 */}
        {(nameFilter || teamFilter) && (
          <p className="text-[10px]" style={{ color: subText }}>
            {filteredPlayers.length}名表示中（全{players.length}名）
          </p>
        )}

        {/* チェックボックスリスト（最大高さ制限 + スクロール） */}
        <div
          className="grid grid-cols-1 md:grid-cols-2 gap-1.5 overflow-y-auto pr-1"
          style={{ maxHeight: '280px' }}
        >
          {filteredPlayers.map((p) => (
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
                className="accent-blue-500 shrink-0"
              />
              <div className="min-w-0">
                <div className="truncate font-medium">{p.name}</div>
                {p.team && <div className="truncate opacity-60">{p.team}</div>}
              </div>
            </label>
          ))}
          {filteredPlayers.length === 0 && (
            <p className="col-span-2 text-xs text-center py-3" style={{ color: subText }}>
              該当する選手がいません
            </p>
          )}
        </div>
      </div>

      {/* フィルター */}
      <div className="flex gap-2 flex-wrap items-end">
        <div className="flex-1 min-w-[180px]">
          <SearchableSelect
            options={players.map((p) => ({
              value: p.id,
              label: p.name,
              searchText: p.team ?? '',
              suffix: p.team ? `（${p.team}）` : undefined,
            }))}
            value={opponentId}
            onChange={(v) => { setOpponentId(v != null ? Number(v) : null); setEnabled(false) }}
            emptyLabel={`${t('prediction.lineup_vs_opponent')}（任意）`}
            placeholder={t('auto.LineupOptimizerPanel.k7')}
          />
        </div>
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
        onClick={() => { if (canRun) setEnabled(true) }}
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

      {/* 結果: ロール別表示 */}
      {result && result.ranked_players.length > 0 && (
        isAnalyst
          ? <AnalystRankingView result={result} isLight={isLight} />
          : <CoachCandidateView result={result} isLight={isLight} />
      )}
    </div>
  )
}
