/**
 * PrematchStatCard — 試合前統計予測カード
 *
 * forecast タブで試合を選択した際に表示する。
 * 対象試合の日付以前のデータのみを使い、相手確定済みの状態で
 * MatchNarrativeCard + 勝率・セット分布サマリーを表示する。
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Database, RefreshCw } from 'lucide-react'
import { apiGet } from '@/api/client'
import { MatchNarrativeCard, type MatchNarrative } from '@/components/analysis/MatchNarrativeCard'
import { WIN, LOSS } from '@/styles/colors'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { useTranslation } from 'react-i18next'

interface PrematchData {
  match_date: string
  opponent_id: number
  opponent_name: string
  tournament_level: string
  cutoff_date: string
  sample_size: number
  h2h_count: number
  win_probability: number | null
  set_distribution: { '2-0': number; '2-1': number; '1-2': number; '0-2': number } | null
  most_likely_scorelines: Array<{
    outcome: string
    probability: number
    set1_score?: string
    set2_score?: string
    set3_score?: string
  }>
  confidence_meta?: { level: string; stars: string; label: string }
  match_narrative: MatchNarrative | null
  computed_at?: string
}

interface Props {
  matchId: number
  playerId: number
  playerName: string
}

export function PrematchStatCard({ matchId, playerId, playerName }: Props) {
  const { t } = useTranslation()

  const isLight = useIsLightMode()
  const subText = isLight ? '#64748b' : '#9ca3af'
  const neutral = isLight ? '#334155' : '#d1d5db'
  const cardBg = isLight ? '#ffffff' : '#1e293b'
  const cardBorder = isLight ? '#e2e8f0' : '#334155'
  const qc = useQueryClient()
  const [force, setForce] = useState(false)

  const queryKey = ['prematch-by-match', matchId, playerId, force]
  const { data: resp, isLoading, isFetching } = useQuery({
    queryKey,
    queryFn: () =>
      apiGet<{ success: boolean; cached: boolean; data: PrematchData }>(
        '/prediction/prematch_by_match',
        { match_id: matchId, player_id: playerId, ...(force ? { force: true } : {}) }
      ),
    enabled: !!matchId && !!playerId,
    staleTime: Infinity,  // DB 保存済みなので自動再取得しない
  })

  function handleForceRecalc() {
    setForce(true)
    qc.invalidateQueries({ queryKey: ['prematch-by-match', matchId, playerId] })
  }

  if (isLoading) {
    return (
      <div className="text-xs text-center py-4" style={{ color: subText }}>
        試合前統計を計算中...
      </div>
    )
  }

  const d = resp?.data
  if (!d) return null

  return (
    <div className="space-y-3">
      {/* カットオフ表示バー */}
      <div
        className="flex items-center gap-2 px-3 py-2 rounded text-[11px]"
        style={{
          background: isLight ? '#f0f9ff' : '#0c1a2e',
          border: `1px solid ${isLight ? '#bae6fd' : '#1e3a5f'}`,
        }}
      >
        <Database size={11} style={{ color: '#3b82f6', flexShrink: 0 }} />
        <span className="flex-1" style={{ color: isLight ? '#1d4ed8' : '#93c5fd' }}>
          統計予測 — {d.cutoff_date} 以前のデータ使用
          {d.h2h_count > 0
            ? `（対戦実績 ${d.h2h_count}試合）`
            : '（対戦実績なし）'}
          {resp?.cached && d.computed_at && (
            <span className="ml-2 opacity-60">
              算出: {d.computed_at.slice(0, 10)}
            </span>
          )}
        </span>
        <button
          onClick={handleForceRecalc}
          disabled={isFetching}
          title={t('auto.PrematchStatCard.k2')}
          className="shrink-0 p-1 rounded hover:opacity-70 transition-opacity disabled:opacity-40"
        >
          <RefreshCw size={11} style={{ color: subText }} className={isFetching ? 'animate-spin' : ''} />
        </button>
      </div>

      {/* データなし */}
      {d.sample_size === 0 && (
        <div
          className="px-4 py-3 rounded text-xs text-center"
          style={{ background: cardBg, border: `1px solid ${cardBorder}`, color: subText }}
        >
          この試合より前のデータがありません（統計予測不可）
        </div>
      )}

      {/* MatchNarrativeCard */}
      {d.match_narrative && (
        <MatchNarrativeCard
          narrative={d.match_narrative}
          playerName={playerName}
          opponentName={d.opponent_name}
        />
      )}

      {/* サマリー: 勝率 + セット分布 */}
      {d.win_probability !== null && d.sample_size > 0 && (
        <div
          className="rounded-lg px-4 py-3 space-y-3"
          style={{ background: cardBg, border: `1px solid ${cardBorder}` }}
        >
          {/* 勝率 + サンプル数 */}
          <div className="flex items-center gap-4">
            <div>
              <p
                className="text-3xl font-bold"
                style={{
                  color: d.win_probability >= 0.55 ? WIN
                    : d.win_probability <= 0.45 ? LOSS
                    : neutral,
                }}
              >
                {Math.round(d.win_probability * 100)}%
              </p>
              <p className="text-[10px] mt-0.5" style={{ color: subText }}>{t('auto.PrematchStatCard.k1')}</p>
            </div>
            <div className="flex flex-col gap-1 text-[11px]" style={{ color: subText }}>
              {d.confidence_meta && (
                <span className="font-semibold text-sm" style={{ color: neutral }}>
                  {d.confidence_meta.stars}
                </span>
              )}
              <span>{d.sample_size}試合のデータ</span>
              {d.confidence_meta && (
                <span>{d.confidence_meta.label}</span>
              )}
            </div>
          </div>

          {/* 最有力スコアライン */}
          {d.most_likely_scorelines.length > 0 && (
            <div className="border-t pt-2" style={{ borderColor: cardBorder }}>
              <p className="text-[10px] font-semibold mb-1.5" style={{ color: subText }}>
                最有力展開
              </p>
              <div className="space-y-1">
                {d.most_likely_scorelines.slice(0, 3).map((sl, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs">
                    <span
                      className="font-bold w-8 shrink-0"
                      style={{ color: sl.outcome.startsWith('2') ? WIN : LOSS }}
                    >
                      {sl.outcome}
                    </span>
                    <span className="font-mono flex-1" style={{ color: neutral }}>
                      {[sl.set1_score, sl.set2_score, sl.set3_score]
                        .filter(Boolean)
                        .join(' / ')}
                    </span>
                    <span className="font-mono shrink-0" style={{ color: subText }}>
                      {Math.round(sl.probability * 100)}%
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
