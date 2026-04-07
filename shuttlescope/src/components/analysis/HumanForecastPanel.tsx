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
import { ChevronDown, ChevronUp, Plus, Trash2 } from 'lucide-react'
import { apiGet, apiPost, apiDelete } from '@/api/client'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { WIN, LOSS } from '@/styles/colors'

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
  { value: 'coach', label: 'コーチ' },
  { value: 'analyst', label: 'アナリスト' },
]
const CONFIDENCE_OPTIONS = [
  { value: 'high', label: '高い' },
  { value: 'medium', label: '中程度' },
  { value: 'low', label: '低い' },
]

// ── フォームセクション ────────────────────────────────────────────────────────

function ForecastForm({ matchId, playerId, onSaved }: Props & { onSaved: () => void }) {
  const { t } = useTranslation()
  const isLight = useIsLightMode()
  const subText = isLight ? '#64748b' : '#9ca3af'
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

  return (
    <div className="space-y-3">
      {/* ロール + 名前 */}
      <div className="flex gap-2">
        <select value={role} onChange={(e) => setRole(e.target.value)} className={inputClass}>
          {ROLE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
        <input
          className={`${inputClass} flex-1`}
          placeholder="名前（任意）"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>

      {/* 勝敗予測トグル */}
      <div className="flex gap-2">
        <button
          onClick={() => setOutcome('win')}
          className={`flex-1 py-1.5 rounded text-sm font-medium border transition-colors ${
            outcome === 'win'
              ? 'border-green-500 bg-green-900/30 text-green-300'
              : 'border-gray-600 bg-gray-700 text-gray-400 hover:border-gray-500'
          }`}
        >
          {t('prediction.human_forecast_win')} (W)
        </button>
        <button
          onClick={() => setOutcome('loss')}
          className={`flex-1 py-1.5 rounded text-sm font-medium border transition-colors ${
            outcome === 'loss'
              ? 'border-red-500 bg-red-900/30 text-red-300'
              : 'border-gray-600 bg-gray-700 text-gray-400 hover:border-gray-500'
          }`}
        >
          {t('prediction.human_forecast_loss')} (L)
        </button>
      </div>

      {/* セットパス + 勝率見込み */}
      <div className="flex gap-2">
        <select value={setPath} onChange={(e) => setSetPath(e.target.value)} className={inputClass}>
          <option value="">セットパス（任意）</option>
          {SET_PATH_OPTIONS.filter(Boolean).map((o) => (
            <option key={o} value={o}>{o}</option>
          ))}
        </select>
        <input
          type="number"
          min={0}
          max={100}
          className={`${inputClass} w-24`}
          placeholder="勝率%"
          value={prob}
          onChange={(e) => setProb(e.target.value)}
        />
        <select value={confidence} onChange={(e) => setConfidence(e.target.value)} className={inputClass}>
          {CONFIDENCE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </div>

      {/* メモ */}
      <textarea
        className={`${inputClass} w-full resize-none`}
        rows={2}
        placeholder={t('prediction.human_forecast_notes')}
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
      />

      <button
        onClick={() => save.mutate()}
        disabled={save.isPending}
        className="w-full py-2 rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-sm font-medium"
      >
        {save.isPending ? '保存中...' : t('prediction.human_forecast_save')}
      </button>
      {save.isError && (
        <p className="text-xs" style={{ color: LOSS }}>保存に失敗しました</p>
      )}
    </div>
  )
}

// ── ベンチマーク表示 ──────────────────────────────────────────────────────────

function BenchmarkSection({ playerId, isLight }: { playerId: number; isLight: boolean }) {
  const { t } = useTranslation()
  const subText = isLight ? '#64748b' : '#9ca3af'
  const neutral = isLight ? '#334155' : '#d1d5db'

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
      <p className="text-xs" style={{ color: subText }}>
        {t('prediction.benchmark_no_data')}
      </p>
    )
  }

  return (
    <div className="space-y-3">
      {/* ロール別サマリーテーブル */}
      {d.summary.length > 0 && (
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wide mb-2" style={{ color: subText }}>
            {t('prediction.benchmark_title')}
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr style={{ color: subText }}>
                  <th className="text-left py-1 pr-3">ロール</th>
                  <th className="text-right pr-3">正解率(人)</th>
                  <th className="text-right pr-3">正解率(モデル)</th>
                  <th className="text-right pr-3">Brier(人)</th>
                  <th className="text-right">Brier(モデル)</th>
                </tr>
              </thead>
              <tbody>
                {d.summary.map((s, i) => (
                  <tr key={i} className="border-t border-gray-700">
                    <td className="py-1 pr-3" style={{ color: neutral }}>
                      {s.role === 'coach' ? 'コーチ' : 'アナリスト'} ({s.n}試合)
                    </td>
                    <td className="text-right pr-3" style={{ color: neutral }}>
                      {Math.round(s.human_accuracy * 100)}%
                    </td>
                    <td
                      className="text-right pr-3 font-medium"
                      style={{ color: s.model_accuracy >= s.human_accuracy ? WIN : LOSS }}
                    >
                      {Math.round(s.model_accuracy * 100)}%
                    </td>
                    <td className="text-right pr-3 font-mono" style={{ color: neutral }}>
                      {s.human_brier.toFixed(3)}
                    </td>
                    <td
                      className="text-right font-mono font-medium"
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
          <p className="text-[10px] font-semibold uppercase tracking-wide mb-1" style={{ color: subText }}>
            試合別比較（直近{Math.min(5, d.match_comparisons.length)}件）
          </p>
          <div className="space-y-1">
            {d.match_comparisons.slice(0, 5).map((c, i) => (
              <div key={i} className="flex items-center gap-2 text-[10px]" style={{ color: subText }}>
                <span className="font-mono">{c.match_date.slice(0, 7)}</span>
                <span>{c.tournament_level}</span>
                <span
                  className="font-bold"
                  style={{ color: c.actual_outcome === 'win' ? WIN : LOSS }}
                >
                  実:{c.actual_outcome === 'win' ? 'W' : 'L'}
                </span>
                <span style={{ color: c.human_correct ? WIN : LOSS }}>
                  人:{c.human_predicted === 'win' ? 'W' : 'L'}{c.human_correct ? '✓' : '✗'}
                </span>
                <span style={{ color: c.model_correct ? WIN : LOSS }}>
                  機:{c.model_win_prob}%{c.model_correct ? '✓' : '✗'}
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
  const subText = isLight ? '#64748b' : '#9ca3af'
  const neutral = isLight ? '#334155' : '#d1d5db'
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
    mutationFn: (id: number) => apiDelete(`/prediction/human_forecast/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['human-forecasts', matchId, playerId] })
      qc.invalidateQueries({ queryKey: ['human-benchmark', playerId] })
    },
  })

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold" style={{ color: subText }}>
          {t('prediction.human_forecast')}
        </p>
        <button
          onClick={() => setShowForm((v) => !v)}
          className="flex items-center gap-1 text-xs px-2 py-1 rounded bg-gray-700 hover:bg-gray-600"
          style={{ color: neutral }}
        >
          <Plus size={11} />
          {t('prediction.human_forecast_add')}
        </button>
      </div>

      {/* 入力フォーム */}
      {showForm && (
        <div className="bg-gray-900 rounded p-3">
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
              className="flex items-center gap-2 text-xs bg-gray-900 rounded px-2 py-1.5"
            >
              <span style={{ color: subText }}>
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
                <span style={{ color: neutral }}>{f.predicted_set_path}</span>
              )}
              {f.predicted_win_probability !== null && (
                <span style={{ color: neutral }}>{f.predicted_win_probability}%</span>
              )}
              {f.confidence_level && (
                <span className="text-[10px]" style={{ color: subText }}>({f.confidence_level})</span>
              )}
              <button
                onClick={() => remove.mutate(f.id)}
                className="ml-auto p-1 rounded hover:bg-gray-700 text-gray-500 hover:text-red-400"
              >
                <Trash2 size={10} />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* ベンチマーク折りたたみ */}
      <button
        className="flex items-center gap-1 text-xs w-full"
        style={{ color: subText }}
        onClick={() => setShowBenchmark((v) => !v)}
      >
        {showBenchmark ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
        {t('prediction.benchmark_title')}
      </button>
      {showBenchmark && (
        <div className="bg-gray-900 rounded p-3">
          <BenchmarkSection playerId={playerId} isLight={isLight} />
        </div>
      )}
    </div>
  )
}
