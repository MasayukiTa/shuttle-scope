/**
 * PredictionPanel — 試合予測メインコンポーネント
 *
 * CoachSummaryStrip: 常時表示の5スロット圧縮サマリー
 * Layer A: 勝率・信頼度・展開パターン・戦術ランキング
 * Layer B: セット分布（折りたたみ）
 * Layer C: 根拠・観察・ドライバー・反事実（折りたたみ）
 * FatigueRiskCard: 疲労リスク
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { NoDataMessage } from '@/components/common/NoDataMessage'
import { SetDistributionBar } from '@/components/analysis/SetDistributionBar'
import { MatchScoreBand } from '@/components/analysis/MatchScoreBand'
import { ScorelineHistogram } from '@/components/analysis/ScorelineHistogram'
import { FatigueRiskCard } from '@/components/analysis/FatigueRiskCard'
import { CoachSummaryStrip } from '@/components/analysis/CoachSummaryStrip'
import { MatchScriptBlock } from '@/components/analysis/MatchScriptBlock'
import { PredictionDriversBlock } from '@/components/analysis/PredictionDriversBlock'
import { CounterfactualShots } from '@/components/analysis/CounterfactualShots'
import { AnalystDepthPanel } from '@/components/analysis/AnalystDepthPanel'
import { WIN, LOSS } from '@/styles/colors'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { useAuth } from '@/hooks/useAuth'

interface PlayerSummary {
  id: number
  name: string
  team?: string
  match_count?: number
}

interface PredictionData {
  win_probability: number
  set_distribution: { '2-0': number; '2-1': number; '1-2': number; '0-2': number }
  score_bands: Record<string, { my_low: number; my_high: number; opp_low: number; opp_high: number; sample: number }>
  win_probability_v2?: number
  feature_breakdown?: {
    base_wr: number
    recent_wr: number
    h2h_wr: number | null
    weights: Record<string, number>
    obs_modifier: number
    raw_blend: number
    final: number
  }
  recent_form?: {
    win_rate: number
    sample: number
    trend: 'improving' | 'declining' | 'stable'
    results: string[]
    overall_wr: number
  }
  set_model_type?: 'observed' | 'momentum'
  score_volatility?: {
    volatility_score: number
    close_match_rate: number
    dominant_match_rate: number
    typical_margin: number
    sample: number
  }
  calibrated_scorelines: Array<{ outcome: string; scoreline: string; count: number; frequency: number }>
  most_likely_scorelines: Array<{
    outcome: string
    probability: number
    set1_score?: string
    set2_score?: string
    set3_score?: string
  }>
  confidence: number
  sample_size: number
  similar_matches: number
  observation_context: Record<string, unknown>
  tactical_notes: Array<{ note: string; estimated_impact: string; basis: string } | string>
  caution_flags: string[]
  prediction_drivers?: {
    primary_type: string
    primary_count: number
    h2h_count: number
    same_level_count: number
    all_count: number
    has_observations: boolean
    drivers: Array<{ label: string; type: string; count: number; weight: string }>
  }
}

interface PredictionResponse {
  success: boolean
  data: PredictionData
  meta: {
    sample_size: number
    confidence: { level: string; stars: string; label: string; warning?: string }
  }
}

interface PredictionPanelProps {
  playerId: number
  playerName: string
  players: PlayerSummary[]
}

const LEVEL_OPTIONS = ['', 'IC', 'IS', 'SJL', '全日本', '国内', 'その他']

function winProbColor(p: number, isLight: boolean): string {
  const neutral = isLight ? '#1e293b' : '#e2e8f0'
  if (p >= 0.55) return WIN
  if (p <= 0.45) return LOSS
  return neutral
}

export function PredictionPanel({ playerId, playerName, players }: PredictionPanelProps) {
  const { t } = useTranslation()
  const isLight = useIsLightMode()
  const { role } = useAuth()
  const isCoach = role === 'coach'

  const [opponentId, setOpponentId] = useState<number | null>(null)
  const [tournamentLevel, setTournamentLevel] = useState<string>('')
  const [showLayerB, setShowLayerB] = useState(!isCoach)
  const [showLayerC, setShowLayerC] = useState(!isCoach)

  const { data: resp, isLoading } = useQuery({
    queryKey: ['prediction-match-preview', playerId, opponentId, tournamentLevel],
    queryFn: () =>
      apiGet<PredictionResponse>('/prediction/match_preview', {
        player_id: playerId,
        ...(opponentId ? { opponent_id: opponentId } : {}),
        ...(tournamentLevel ? { tournament_level: tournamentLevel } : {}),
      }),
    enabled: !!playerId,
  })

  // 疲労リスク（MatchScriptBlock / FatigueRiskCard 用）
  const { data: fatigueResp } = useQuery({
    queryKey: ['prediction-fatigue-risk-panel', playerId, tournamentLevel],
    queryFn: () =>
      apiGet<{ success: boolean; data: { breakdown: { temporal_drop: number; long_rally_penalty: number; pressure_drop: number; total_rallies: number } } }>(
        '/prediction/fatigue_risk',
        { player_id: playerId, ...(tournamentLevel ? { tournament_level: tournamentLevel } : {}) }
      ),
    enabled: !!playerId,
  })

  const d = resp?.data
  const meta = resp?.meta
  const neutral = isLight ? '#334155' : '#d1d5db'
  const subText = isLight ? '#64748b' : '#9ca3af'

  if (isLoading) {
    return (
      <div className="text-gray-500 text-sm py-8 text-center">{t('prediction.loading')}</div>
    )
  }

  if (!d || d.sample_size === 0) {
    return (
      <div className="space-y-4">
        <FilterBar
          players={players}
          playerId={playerId}
          opponentId={opponentId}
          onOpponentChange={setOpponentId}
          tournamentLevel={tournamentLevel}
          onLevelChange={setTournamentLevel}
          t={t}
          isLight={isLight}
        />
        <NoDataMessage sampleSize={0} minRequired={1} unit="試合" />
      </div>
    )
  }

  const winPct = Math.round(d.win_probability * 100)
  const topOutcome = Object.entries(d.set_distribution).sort((a, b) => b[1] - a[1])[0]
  const fatigueBreakdown = fatigueResp?.data?.breakdown ?? null

  return (
    <div className="space-y-4">
      {/* CoachSummaryStrip — 常時表示（折りたたみなし） */}
      <CoachSummaryStrip
        winProbability={d.win_probability_v2 ?? d.win_probability}
        confidence={d.confidence}
        confidenceStars={meta?.confidence.stars ?? ''}
        setDistribution={d.set_distribution}
        cautionFlags={d.caution_flags}
        tacticalNotes={d.tactical_notes}
        sampleSize={d.sample_size}
        recentForm={d.recent_form}
      />

      {/* フィルターバー */}
      <FilterBar
        players={players}
        playerId={playerId}
        opponentId={opponentId}
        onOpponentChange={setOpponentId}
        tournamentLevel={tournamentLevel}
        onLevelChange={setTournamentLevel}
        t={t}
        isLight={isLight}
      />

      {/* Layer A: コーチ向けサマリー */}
      <div className="bg-gray-800 rounded-lg p-4 space-y-4">
        <div className="flex items-center gap-3 flex-wrap">
          {meta && <ConfidenceBadge sampleSize={d.sample_size} />}
          <span className="text-xs" style={{ color: subText }}>
            {t('prediction.sample_size')}: {d.sample_size}試合
          </span>
          {d.similar_matches > 0 && (
            <span className="text-xs" style={{ color: subText }}>
              {t('prediction.similar_matches')}: {d.similar_matches}
            </span>
          )}
        </div>

        {/* 勝率大表示 */}
        <div className="grid grid-cols-3 gap-4 text-center">
          <div>
            <p
              className="text-4xl font-bold"
              style={{ color: winProbColor(d.win_probability, isLight) }}
            >
              {winPct}%
            </p>
            <p className="text-[11px] mt-1" style={{ color: subText }}>
              {t('prediction.win_probability')}
            </p>
          </div>
          <div>
            <p className="text-2xl font-bold" style={{ color: neutral }}>
              {meta?.confidence.stars ?? '—'}
            </p>
            <p className="text-[11px] mt-1" style={{ color: subText }}>
              {t('prediction.confidence')}
            </p>
            <p className="text-xs font-mono mt-0.5" style={{ color: subText }}>
              {Math.round(d.confidence * 100)}%
            </p>
          </div>
          <div>
            <p className="text-2xl font-bold" style={{ color: neutral }}>
              {topOutcome ? topOutcome[0] : '—'}
            </p>
            <p className="text-[11px] mt-1" style={{ color: subText }}>
              {t('prediction.most_likely')}
            </p>
            {topOutcome && (
              <p className="text-xs font-mono mt-0.5" style={{ color: subText }}>
                {Math.round(topOutcome[1] * 100)}%
              </p>
            )}
          </div>
        </div>

        {/* スコアボラティリティ */}
        {d.score_volatility && d.score_volatility.sample >= 3 && (
          <div className="border-t border-gray-700 pt-3">
            <p className="text-xs font-medium mb-2" style={{ color: subText }}>
              {t('prediction.score_volatility')}
            </p>
            <div className="flex items-center gap-4 flex-wrap">
              <div className="flex items-center gap-2">
                <div className="w-20 h-1.5 bg-gray-700 rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${Math.round(d.score_volatility.volatility_score * 100)}%`,
                      background: d.score_volatility.volatility_score >= 0.6
                        ? '#d97706'
                        : d.score_volatility.volatility_score >= 0.4
                        ? '#d97706'
                        : '#22c55e',
                    }}
                  />
                </div>
                <span className="text-xs font-medium" style={{ color: neutral }}>
                  {d.score_volatility.volatility_score >= 0.5
                    ? t('prediction.volatility_volatile')
                    : t('prediction.volatility_stable')}
                </span>
              </div>
              <span className="text-[11px]" style={{ color: subText }}>
                {t('prediction.close_match_rate')} {Math.round(d.score_volatility.close_match_rate * 100)}%
              </span>
              <span className="text-[11px]" style={{ color: subText }}>
                {t('prediction.dominant_match_rate')} {Math.round(d.score_volatility.dominant_match_rate * 100)}%
              </span>
            </div>
          </div>
        )}

        {/* 最頻スコアライン */}
        {d.most_likely_scorelines.length > 0 && (
          <div className="border-t border-gray-700 pt-3">
            <p className="text-xs font-medium mb-2" style={{ color: subText }}>
              {t('prediction.most_likely')}
            </p>
            <div className="space-y-1">
              {d.most_likely_scorelines.map((sl, i) => (
                <div key={i} className="flex items-center gap-2 text-xs">
                  <span
                    className="font-bold w-8 shrink-0"
                    style={{ color: sl.outcome.startsWith('2') ? WIN : LOSS }}
                  >
                    {sl.outcome}
                  </span>
                  <span className="font-mono" style={{ color: neutral }}>
                    {[sl.set1_score, sl.set2_score, sl.set3_score]
                      .filter(Boolean)
                      .join(' / ')}
                  </span>
                  <span className="ml-auto font-mono" style={{ color: subText }}>
                    {Math.round(sl.probability * 100)}%
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 試合展開パターン (MatchScriptBlock) */}
        <div className="border-t border-gray-700 pt-3">
          <p className="text-xs font-medium mb-2" style={{ color: subText }}>
            {t('prediction.match_script')}
          </p>
          <MatchScriptBlock
            winProbability={d.win_probability}
            fatigueBreakdown={fatigueBreakdown}
          />
        </div>

        {/* 戦術推奨ランキング */}
        {d.tactical_notes.length > 0 && (
          <div className="border-t border-gray-700 pt-3">
            <p className="text-xs font-semibold mb-2" style={{ color: subText }}>
              {t('prediction.tactical_ranking')}
            </p>
            <ul className="space-y-1.5">
              {d.tactical_notes.map((item, i) => {
                const note = typeof item === 'string' ? item : item.note
                const impact = typeof item === 'string' ? null : item.estimated_impact
                return (
                  <li key={i} className="flex items-start gap-2 text-xs">
                    <span className="text-gray-500 shrink-0 w-4 text-right">{i + 1}.</span>
                    <span style={{ color: neutral }}>{note}</span>
                    {impact && (
                      <span
                        className="shrink-0 text-[10px] px-1 py-0.5 rounded font-medium"
                        style={{
                          color: impact === '高' ? WIN : impact === '低' ? '#6b7280' : '#d97706',
                          backgroundColor: impact === '高' ? WIN + '20' : impact === '低' ? '#37415120' : '#d9770620',
                          border: `1px solid ${impact === '高' ? WIN + '60' : impact === '低' ? '#37415160' : '#d9770660'}`,
                        }}
                      >
                        {impact}
                      </span>
                    )}
                  </li>
                )
              })}
            </ul>
          </div>
        )}

        {/* 注意フラグ */}
        {d.caution_flags.length > 0 && (
          <div className="border-t border-gray-700 pt-3 space-y-1">
            {d.caution_flags.map((flag, i) => (
              <p key={i} className="text-xs" style={{ color: LOSS }}>
                ⚠ {flag}
              </p>
            ))}
          </div>
        )}
      </div>

      {/* Layer B: セット分布（折りたたみ可） */}
      <div className="bg-gray-800 rounded-lg overflow-hidden">
        <button
          className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium"
          style={{ color: neutral }}
          onClick={() => setShowLayerB((v) => !v)}
        >
          <span>{t('prediction.set_distribution')}</span>
          {showLayerB ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>
        {showLayerB && (
          <div className="px-4 pb-4 space-y-4">
            <SetDistributionBar distribution={d.set_distribution} />
            {Object.keys(d.score_bands).length > 0 && (
              <div className="border-t border-gray-700 pt-3">
                <p className="text-xs font-medium mb-2" style={{ color: subText }}>
                  {t('prediction.score_bands')}
                </p>
                <MatchScoreBand
                  scoreBands={d.score_bands}
                  playerName={playerName}
                  opponentName={opponentId ? (players.find((p) => p.id === opponentId)?.name ?? '相手') : '相手'}
                />
              </div>
            )}
            {d.calibrated_scorelines.length > 0 && (
              <div className="border-t border-gray-700 pt-3">
                <ScorelineHistogram data={d.calibrated_scorelines} />
              </div>
            )}
          </div>
        )}
      </div>

      {/* Layer C: 根拠・戦術ノート（折りたたみ可） */}
      <div className="bg-gray-800 rounded-lg overflow-hidden">
        <button
          className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium"
          style={{ color: neutral }}
          onClick={() => setShowLayerC((v) => !v)}
        >
          <span>{t('prediction.layer_c')}</span>
          {showLayerC ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>
        {showLayerC && (
          <div className="px-4 pb-4 space-y-4">
            {/* 戦術ノート */}
            {d.tactical_notes.length > 0 && (
              <div>
                <p className="text-xs font-semibold mb-2" style={{ color: subText }}>
                  {t('prediction.tactical_notes')}
                </p>
                <ul className="space-y-1">
                  {d.tactical_notes.map((item, i) => {
                    const note = typeof item === 'string' ? item : item.note
                    const basis = typeof item === 'string' ? null : item.basis
                    return (
                      <li key={i} className="text-xs flex gap-2" style={{ color: neutral }}>
                        <span style={{ color: subText }}>•</span>
                        <span>
                          {note}
                          {basis && <span className="ml-1 text-[10px]" style={{ color: subText }}>({basis})</span>}
                        </span>
                      </li>
                    )
                  })}
                </ul>
              </div>
            )}

            {/* 観察コンテキスト */}
            {Object.keys(d.observation_context).length > 0 && (
              <div className="border-t border-gray-700 pt-3">
                <p className="text-xs font-semibold mb-2" style={{ color: subText }}>
                  {t('prediction.observation_context')}
                  <span className="ml-1 text-[10px] font-normal">
                    ({t('prediction.observation_note')})
                  </span>
                </p>
                <ObservationContextBlock context={d.observation_context} isLight={isLight} />
              </div>
            )}

            {/* 予測ドライバー・データソース内訳 */}
            {d.prediction_drivers ? (
              <div className="border-t border-gray-700 pt-3">
                <p className="text-xs font-semibold mb-2" style={{ color: subText }}>
                  {t('prediction.prediction_drivers')}
                </p>
                <PredictionDriversBlock
                  primaryType={d.prediction_drivers.primary_type}
                  primaryCount={d.prediction_drivers.primary_count}
                  h2hCount={d.prediction_drivers.h2h_count}
                  sameLevelCount={d.prediction_drivers.same_level_count}
                  allCount={d.prediction_drivers.all_count}
                  hasObservations={d.prediction_drivers.has_observations}
                  drivers={d.prediction_drivers.drivers}
                />
                {meta?.confidence.warning && (
                  <p className="text-[11px] mt-2" style={{ color: subText }}>
                    ⚠ {meta.confidence.warning}
                  </p>
                )}
              </div>
            ) : (
              <div className="border-t border-gray-700 pt-3">
                <p className="text-[11px]" style={{ color: subText }}>
                  {d.similar_matches >= 3
                    ? t('prediction.data_source_h2h')
                    : t('prediction.data_source_all')}
                  {' — '}
                  {d.sample_size}試合から算出（統計ベース）
                </p>
                {meta?.confidence.warning && (
                  <p className="text-[11px] mt-1" style={{ color: subText }}>
                    ⚠ {meta.confidence.warning}
                  </p>
                )}
              </div>
            )}

            {/* Phase E: 反事実的ショット比較（アナリストのみ） */}
            {role === 'analyst' && (
              <div className="border-t border-gray-700 pt-3">
                <CounterfactualShots playerId={playerId} />
              </div>
            )}

            {/* Phase 1 Rebuild: アナリスト深掘りパネル */}
            {role === 'analyst' && (
              <div className="border-t border-gray-700 pt-3">
                <AnalystDepthPanel
                  playerId={playerId}
                  opponentId={opponentId}
                  tournamentLevel={tournamentLevel || undefined}
                />
              </div>
            )}
          </div>
        )}
      </div>

      {/* Phase C: 疲労・崩壊リスクカード */}
      <FatigueRiskCard playerId={playerId} tournamentLevel={tournamentLevel || undefined} />
    </div>
  )
}

// ─── フィルターバー ───────────────────────────────────────────────────────────

function FilterBar({
  players,
  playerId,
  opponentId,
  onOpponentChange,
  tournamentLevel,
  onLevelChange,
  t,
  isLight,
}: {
  players: PlayerSummary[]
  playerId: number
  opponentId: number | null
  onOpponentChange: (id: number | null) => void
  tournamentLevel: string
  onLevelChange: (v: string) => void
  t: (k: string, fb?: string) => string
  isLight: boolean
}) {
  const selectClass = `text-xs rounded px-2 py-1.5 focus:outline-none ${
    isLight
      ? 'bg-white border border-gray-300 text-gray-800'
      : 'bg-gray-700 border border-gray-600 text-gray-200'
  }`
  return (
    <div className="flex gap-2 flex-wrap items-center">
      <select
        value={opponentId ?? ''}
        onChange={(e) => onOpponentChange(e.target.value ? Number(e.target.value) : null)}
        className={selectClass}
      >
        <option value="">{t('prediction.select_opponent')}</option>
        {players
          .filter((p) => p.id !== playerId)
          .map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}{p.team ? `（${p.team}）` : ''}
            </option>
          ))}
      </select>
      <select
        value={tournamentLevel}
        onChange={(e) => onLevelChange(e.target.value)}
        className={selectClass}
      >
        <option value="">{t('prediction.select_level')}</option>
        {LEVEL_OPTIONS.filter(Boolean).map((lv) => (
          <option key={lv} value={lv}>{lv}</option>
        ))}
      </select>
    </div>
  )
}

// ─── 観察コンテキスト表示 ─────────────────────────────────────────────────────

function ObservationContextBlock({
  context,
  isLight,
}: {
  context: Record<string, unknown>
  isLight: boolean
}) {
  const neutral = isLight ? '#334155' : '#d1d5db'
  const subColor = isLight ? '#64748b' : '#9ca3af'

  const OBS_LABELS: Record<string, string> = {
    handedness: '利き手',
    physical_caution: '身体的注意',
    tactical_style: '戦術スタイル',
    court_preference: 'コート位置',
    self_condition: '自コンディション',
    self_timing: 'タイミング感覚',
  }
  const VAL_LABELS: Record<string, string> = {
    R: '右利き', L: '左利き', unknown: '不明',
    none: 'なし', light: '軽度', moderate: '中程度', heavy: '重度',
    attacker: '攻撃型', defender: '守備型', balanced: 'バランス型',
    front: '前衛寄り', rear: '後衛寄り',
    great: '良好', normal: '普通', poor: '不調',
    sharp: '切れている', off: '乱れ',
  }

  const renderSection = (label: string, obs: Record<string, { value: string; confidence: string }>) => (
    <div className="space-y-1">
      <p className="text-[10px] font-semibold uppercase tracking-wide" style={{ color: subColor }}>
        {label}
      </p>
      {Object.entries(obs).map(([key, entry]) => (
        <div key={key} className="flex items-center gap-2 text-xs">
          <span style={{ color: subColor }}>{OBS_LABELS[key] ?? key}:</span>
          <span style={{ color: neutral }}>{VAL_LABELS[entry.value] ?? entry.value}</span>
          <span className="text-[10px]" style={{ color: subColor }}>({entry.confidence})</span>
        </div>
      ))}
    </div>
  )

  return (
    <div className="space-y-3">
      {context.opponent && renderSection('相手', context.opponent as Record<string, { value: string; confidence: string }>)}
      {context.self && renderSection('自分', context.self as Record<string, { value: string; confidence: string }>)}
    </div>
  )
}
