/**
 * HumanForecastPanel — Phase S2: コーチ/アナリストの試合前予測入力 + ベンチマーク表示
 *
 * 試合IDと対象選手IDが必要。
 * - フォーム: 勝敗予測 / セットパス / 勝率見込み / 確信度
 * - ベンチマーク: 同選手の過去予測における人間 vs モデル 精度比較
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import i18n from '@/i18n'
import { apiGet, apiPost, apiDelete, newIdempotencyKey } from '@/api/client'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { WIN, LOSS } from '@/styles/colors'
import { MIcon } from '@/components/common/MIcon'

// ── 型定義 ──────────────────────────────────────────────────────────────────

interface ForecastRecord {
  id: number
  match_id: number
  player_id: number
  forecaster_role: string
  forecaster_name: string | null
  predicted_outcome: 'win' | 'loss'
  predicted_set_path: string | null
  predicted_win_probability: number | null
  confidence_level: string | null
  notes: string | null
  created_at: string | null
}

interface BenchmarkComparison {
  match_id: number
  match_date: string
  tournament_level: string
  actual_outcome: string
  forecaster_role: string
  human_predicted: string
  human_set_path: string | null
  human_win_prob: number | null
  human_correct: boolean
  human_brier: number
  model_win_prob: number
  model_predicted: string
  model_correct: boolean
  model_brier: number
}

interface BenchmarkSummary {
  role: string
  n: number
  human_accuracy: number
  model_accuracy: number
  human_brier: number
  model_brier: number
  model_advantage: number
}

interface Props {
  matchId: number
  playerId: number
}

const SET_PATH_OPTIONS = ['', '2-0', '2-1', '1-2', '0-2']
const ROLE_OPTIONS = [
  { value: 'coach', label: i18n.t('auto.HumanForecastPanel.k10') },
  { value: 'analyst', label: i18n.t('auto.HumanForecastPanel.k11') },
]
const CONFIDENCE_OPTIONS = [
  { value: 'high', label: i18n.t('auto.HumanForecastPanel.k12') },
  { value: 'medium', label: i18n.t('auto.HumanForecastPanel.k13') },
  { value: 'low', label: i18n.t('auto.HumanForecastPanel.k14') },
]

// ── フォームセクション ────────────────────────────────────────────────────────

function ForecastForm({ matchId, playerId, onSaved }: Props & { onSaved: () => void }) {
  const { t } = useTranslation()
  const isLight = useIsLightMode()
  const _subText = isLight ? '#64748b' : '#9ca3af'
  const inputClass = `text-sm rounded px-2 py-1.5 focus:outline-none ${
    isLight
      ? 'bg-white border border-gray-300 text-gray-800'
      : 'bg-gray-700 border border-gray-600 text-gray-200'
  }`

  const [role, setRole] = useState('coach')
  const [name, setName] = useState('')
  const [outcome, setOutcome] = useState<'win' | 'loss'>('win')
  const [setPath, setSetPath] = useState('')
  const [prob, setProb] = useState<string>('')
  const [confidence, setConfidence] = useState('medium')
  const [notes, setNotes] = useState('')

  const qc = useQueryClient()
  const save = useMutation({
    mutationFn: () =>
      apiPost('/prediction/human_forecast', {
        match_id: matchId,
        player_id: playerId,
        forecaster_role: role,
        forecaster_name: name || null,
        predicted_outcome: outcome,
        predicted_set_path: setPath || null,
        predicted_win_probability: prob ? parseInt(prob, 10) : null,
        confidence_level: confidence,
        notes: notes || null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['human-forecasts', matchId, playerId] })
      qc.invalidateQueries({ queryKey: ['human-benchmark', playerId] })
      onSaved()
    },
  })

  const inputClassTokenized = `text-sm rounded-ss-md px-2 py-1.5 focus:outline-none transition-colors duration-base ease-out border border-[var(--ss-border)] bg-[var(--ss-surface-1)] text-[var(--ss-t1)] focus:border-[var(--ss-brand)]`

  return (
    <div className="space-y-3">
      {/* ロール + 名前 */}
      <div className="flex gap-2">
        <select value={role} onChange={(e) => setRole(e.target.value)} className={inputClassTokenized}>
          {ROLE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
        <input
          className={`${inputClassTokenized} flex-1`}
          placeholder={t('auto.HumanForecastPanel.k8')}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>

      {/* 勝敗予測トグル */}
      <div className="flex gap-2">
        <button
          onClick={() => setOutcome('win')}
          className={`flex-1 py-1.5 rounded-ss-md text-sm font-medium border transition-colors duration-base ease-out ${
            outcome === 'win'
              ? 'border-[var(--ss-good)] bg-[var(--ss-brand-tint)] text-[var(--ss-good)]'
              : 'border-[var(--ss-border)] bg-[var(--ss-surface-2)] text-[var(--ss-t3)] hover:border-[var(--ss-brand)]'
          }`}
        >
          {t('prediction.human_forecast_win')}{t('auto.HumanForecastPanel.w_label')}
        </button>
        <button
          onClick={() => setOutcome('loss')}
          className={`flex-1 py-1.5 rounded-ss-md text-sm font-medium border transition-colors duration-base ease-out ${
            outcome === 'loss'
              ? 'border-[var(--ss-bad)] bg-[var(--ss-brand-tint)] text-[var(--ss-bad)]'
              : 'border-[var(--ss-border)] bg-[var(--ss-surface-2)] text-[var(--ss-t3)] hover:border-[var(--ss-brand)]'
          }`}
        >
          {t('prediction.human_forecast_loss')}{t('auto.HumanForecastPanel.l_label')}
        </button>
      </div>

      {/* セットパス + 勝率見込み */}
      <div className="flex gap-2">
        <select value={setPath} onChange={(e) => setSetPath(e.target.value)} className={inputClassTokenized}>
          <option value="">{t('auto.HumanForecastPanel.k1')}</option>
          {SET_PATH_OPTIONS.filter(Boolean).map((o) => (
            <option key={o} value={o}>{o}</option>
          ))}
        </select>
        <input
          type="number"
          min={0}
          max={100}
          className={`${inputClassTokenized} w-24`}
          placeholder={t('auto.HumanForecastPanel.k9')}
          value={prob}
          onChange={(e) => setProb(e.target.value)}
        />
        <select value={confidence} onChange={(e) => setConfidence(e.target.value)} className={inputClassTokenized}>
          {CONFIDENCE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </div>

      {/* メモ */}
      <textarea
        className={`${inputClassTokenized} w-full resize-none`}
        rows={2}
        placeholder={t('prediction.human_forecast_notes')}
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
      />

      <button
        onClick={() => save.mutate()}
        disabled={save.isPending}
        className="w-full py-2 rounded-ss-md bg-[var(--ss-brand)] hover:bg-[var(--ss-brand-hover)] disabled:opacity-50 text-white text-sm font-medium transition-colors duration-base ease-out"
      >
        {save.isPending ? '保存中...' : t('prediction.human_forecast_save')}
      </button>
      {save.isError && (
        <p className="text-xs text-[var(--ss-bad)]">{t('auto.HumanForecastPanel.k2')}</p>
      )}
    </div>
  )
}

// ── ベンチマーク表示 ──────────────────────────────────────────────────────────

function BenchmarkSection({ playerId, isLight }: { playerId: number; isLight: boolean }) {
  const { t } = useTranslation()

  const { data: resp } = useQuery({
    queryKey: ['human-benchmark', playerId],
    queryFn: () =>
      apiGet<{ success: boolean; data: { summary: BenchmarkSummary[]; match_comparisons: BenchmarkComparison[]; total_forecasts: number } }>(
        `/prediction/benchmark/${playerId}`
      ),
  })

  const d = resp?.data
  if (!d || d.total_forecasts === 0) {
    return (
      <p className="text-xs text-[var(--ss-t3)]">
        {t('prediction.benchmark_no_data')}
      </p>
    )
  }

  return (
    <div className="space-y-3">
      {/* ロール別サマリーテーブル */}
      {d.summary.length > 0 && (
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wide mb-2 text-[var(--ss-t3)]">
            {t('prediction.benchmark_title')}
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-[var(--ss-t3)]">
                  <th className="text-left py-1 pr-3">{t('auto.HumanForecastPanel.k3')}</th>
                  <th className="text-right pr-3">{t('auto.HumanForecastPanel.k4')}</th>
                  <th className="text-right pr-3">{t('auto.HumanForecastPanel.k5')}</th>
                  <th className="text-right pr-3">{t('auto.HumanForecastPanel.k6')}</th>
                  <th className="text-right">{t('auto.HumanForecastPanel.k7')}</th>
                </tr>
              </thead>
              <tbody>
                {d.summary.map((s, i) => (
                  <tr key={i} className="border-t border-[var(--ss-border)]">
                    <td className="py-1 pr-3 text-[var(--ss-t2)]">
                      <span className="cell-name-clip" title={`${s.role === 'coach' ? 'コーチ' : 'アナリスト'} (${t('auto._shared.n_matches', { n: s.n })})`}>
                        {t('auto.HumanForecastPanel.evaluator', { label: s.role === 'coach' ? t('roles.coach') : t('roles.analyst'), n: s.n })}
                      </span>
                    </td>
                    <td className="text-right pr-3 ss-num text-[var(--ss-t2)]">
                      {Math.round(s.human_accuracy * 100)}%
                    </td>
                    <td
                      className="text-right pr-3 font-medium ss-num"
                      style={{ color: s.model_accuracy >= s.human_accuracy ? WIN : LOSS }}
                    >
                      {Math.round(s.model_accuracy * 100)}%
                    </td>
                    <td className="text-right pr-3 ss-num text-[var(--ss-t2)]">
                      {s.human_brier.toFixed(3)}
                    </td>
                    <td
                      className="text-right font-medium ss-num"
                      style={{ color: s.model_brier <= s.human_brier ? WIN : LOSS }}
                    >
                      {s.model_brier.toFixed(3)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 直近の比較一覧（最大5件） */}
      {d.match_comparisons.length > 0 && (
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wide mb-1 text-[var(--ss-t3)]">
            {t('auto.HumanForecastPanel.match_compare', { n: Math.min(5, d.match_comparisons.length) })}
          </p>
          <div className="space-y-1">
            {d.match_comparisons.slice(0, 5).map((c, i) => (
              <div key={i} className="flex items-center gap-2 text-[10px] text-[var(--ss-t3)]">
                <span className="font-mono ss-num">{c.match_date.slice(0, 7)}</span>
                <span>{c.tournament_level}</span>
                <span
                  className="font-bold"
                  style={{ color: c.actual_outcome === 'win' ? WIN : LOSS }}
                >
                  {t('auto.HumanForecastPanel.actual_label')}{c.actual_outcome === 'win' ? 'W' : 'L'}
                </span>
                <span style={{ color: c.human_correct ? WIN : LOSS }}>
                  {t('auto.HumanForecastPanel.human_label')}{c.human_predicted === 'win' ? 'W' : 'L'}<MIcon name={c.human_correct ? 'check' : 'close'} size={12} />
                </span>
                <span style={{ color: c.model_correct ? WIN : LOSS }} className="inline-flex items-center gap-0.5">
                  {t('auto.HumanForecastPanel.model_label')}{c.model_win_prob}%<MIcon name={c.model_correct ? 'check' : 'close'} size={12} />
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ── メインコンポーネント ──────────────────────────────────────────────────────

export function HumanForecastPanel({ matchId, playerId }: Props) {
  const { t } = useTranslation()
  const isLight = useIsLightMode()
  const qc = useQueryClient()

  const [showForm, setShowForm] = useState(false)
  const [showBenchmark, setShowBenchmark] = useState(false)

  const { data: forecastsResp } = useQuery({
    queryKey: ['human-forecasts', matchId, playerId],
    queryFn: () =>
      apiGet<{ success: boolean; data: ForecastRecord[] }>(
        `/prediction/human_forecast/${matchId}`,
        { player_id: playerId }
      ),
  })
  const forecasts = forecastsResp?.data ?? []

  const remove = useMutation({
    mutationFn: (id: number) =>
      apiDelete(`/prediction/human_forecast/${id}`, { 'X-Idempotency-Key': newIdempotencyKey() }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['human-forecasts', matchId, playerId] })
      qc.invalidateQueries({ queryKey: ['human-benchmark', playerId] })
    },
  })

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-[var(--ss-t3)]">
          {t('prediction.human_forecast')}
        </p>
        <button
          onClick={() => setShowForm((v) => !v)}
          className="flex items-center gap-1 text-xs px-2 py-1 rounded-ss-md bg-[var(--ss-surface-2)] hover:bg-[var(--ss-surface-3)] transition-colors duration-base ease-out text-[var(--ss-t2)]"
        >
          <MIcon name="add" size={11} />
          {t('prediction.human_forecast_add')}
        </button>
      </div>

      {/* 入力フォーム */}
      {showForm && (
        <div className="bg-[var(--ss-surface-2)] rounded-ss-lg p-3 border border-[var(--ss-border)]">
          <ForecastForm
            matchId={matchId}
            playerId={playerId}
            onSaved={() => setShowForm(false)}
          />
        </div>
      )}

      {/* 保存済み予測リスト */}
      {forecasts.length > 0 && (
        <div className="space-y-1">
          {forecasts.map((f) => (
            <div
              key={f.id}
              className="flex items-center gap-2 text-xs bg-[var(--ss-surface-2)] rounded-ss-md px-2 py-1.5 border border-[var(--ss-border)]"
            >
              <span className="text-[var(--ss-t3)]">
                {f.forecaster_role === 'coach' ? 'コーチ' : 'アナリスト'}
                {f.forecaster_name && ` (${f.forecaster_name})`}:
              </span>
              <span
                className="font-bold"
                style={{ color: f.predicted_outcome === 'win' ? WIN : LOSS }}
              >
                {f.predicted_outcome === 'win' ? 'W' : 'L'}
              </span>
              {f.predicted_set_path && (
                <span className="ss-num text-[var(--ss-t2)]">{f.predicted_set_path}</span>
              )}
              {f.predicted_win_probability !== null && (
                <span className="ss-num text-[var(--ss-t2)]">{f.predicted_win_probability}%</span>
              )}
              {f.confidence_level && (
                <span className="text-[10px] text-[var(--ss-t3)]">({f.confidence_level})</span>
              )}
              <button
                onClick={() => remove.mutate(f.id)}
                className="ml-auto p-1 rounded-ss-md hover:bg-[var(--ss-surface-3)] text-[var(--ss-t3)] hover:text-[var(--ss-bad)] transition-colors duration-base ease-out"
              >
                <MIcon name="delete" size={10} />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* ベンチマーク折りたたみ */}
      <button
        className="flex items-center gap-1 text-xs w-full text-[var(--ss-t3)]"
        onClick={() => setShowBenchmark((v) => !v)}
      >
        {showBenchmark ? <MIcon name="expand_less" size={11} /> : <MIcon name="expand_more" size={11} />}
        {t('prediction.benchmark_title')}
      </button>
      {showBenchmark && (
        <div className="bg-[var(--ss-surface-2)] rounded-ss-lg p-3 border border-[var(--ss-border)]">
          <BenchmarkSection playerId={playerId} isLight={isLight} />
        </div>
      )}
    </div>
  )
}
