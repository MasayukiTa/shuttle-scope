// スコア推移グラフコンポーネント（ラリーごとの点差変化をラインチャートで表示）
import { useState, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  CartesianGrid,
} from 'recharts'
import { useTranslation } from 'react-i18next'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { WIN, LOSS } from '@/styles/colors'

interface ScoreProgressionProps {
  matchId: number
  /**
   * M-001ダッシュボード用: 折れ線グラフのラリー点クリック時に呼び出す。
   * セットID・セット番号・ラリー番号・その時点のスコアを渡す。
   * このプロップが渡された場合はクリック可能になりセット間速報を表示できる。
   */
  onSetPointClick?: (setId: number, setNum: number, rallyNum: number, scoreA: number, scoreB: number) => void
}

interface RallyPoint {
  rally_num: number
  rally_id?: number
  score_a: number
  score_b: number
  winner: string
  server: string
  end_type: string
  rally_length: number
  point_diff: number
  video_timestamp_start?: number
}

interface StrokeDetail {
  stroke_num: number
  player: string   // player_a / player_b
  shot_type: string
  hit_zone: string | null
  land_zone: string | null
  shot_quality: string | null
}

interface RallyStrokesResponse {
  success: boolean
  data: { rally_id: number; strokes: StrokeDetail[] }
}

interface SetData {
  set_id: number
  set_num: number
  rallies: RallyPoint[]
  momentum_changes: number[]
}

interface ScoreProgressionResponse {
  success: boolean
  data: { sets: SetData[] }
  meta: { sample_size: number }
}

const TOOLTIP_STYLE = {
  backgroundColor: '#1f2937',
  border: '1px solid #374151',
  borderRadius: '6px',
  color: '#f9fafb',
  fontSize: 12,
}

function CustomTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null
  const d = payload[0]?.payload as RallyPoint
  if (!d) return null
  return (
    <div style={TOOLTIP_STYLE} className="px-3 py-2">
      <p className="font-semibold mb-1" style={{ color: '#f9fafb' }}>ラリー {d.rally_num}</p>
      <p style={{ color: WIN }}>A: {d.score_a}</p>
      <p style={{ color: LOSS }}>B: {d.score_b}</p>
      <p style={{ color: '#d1d5db' }}>点差: {d.point_diff > 0 ? '+' : ''}{d.point_diff}</p>
    </div>
  )
}

// ─── ラリー詳細バナー ────────────────────────────────────────────────────────

function RallyDetailBanner({
  rally,
  onClose,
  t,
}: {
  rally: RallyPoint & { set_num: number }
  onClose: () => void
  t: (key: string, fallback?: string) => string
}) {
  const { data: strokesResp, isLoading } = useQuery({
    queryKey: ['rally-strokes', rally.rally_id],
    queryFn: () => apiGet<RallyStrokesResponse>('/analysis/rally_strokes', { rally_id: rally.rally_id! }),
    enabled: rally.rally_id != null,
  })

  const strokes = strokesResp?.data?.strokes ?? []
  const winnerLabel = rally.winner === 'player_a' ? 'A' : 'B'
  const serverLabel = rally.server === 'player_a' ? 'A' : 'B'
  const endTypeLabel = t(`end_types.${rally.end_type}`, rally.end_type)

  return (
    <div
      className="mt-2 rounded-lg border border-gray-700 bg-gray-800/80 p-3 text-xs relative"
      style={{ backdropFilter: 'blur(4px)' }}
    >
      <button
        onClick={onClose}
        className="absolute top-2 right-2 text-gray-500 hover:text-gray-300 text-sm leading-none"
        title="閉じる"
      >✕</button>

      {/* ヘッダー */}
      <div className="flex items-center gap-2 mb-2 pr-4">
        <span className="font-semibold text-gray-200">
          Set {rally.set_num} Rally {rally.rally_num}
        </span>
        <span className="text-gray-500">|</span>
        <span className="text-gray-400">{serverLabel} サーブ</span>
        <span className="text-gray-500">|</span>
        <span className="text-gray-400">{rally.rally_length} 打</span>
        <span className="text-gray-500">|</span>
        <span className="text-gray-400">{endTypeLabel}</span>
        <span className="text-gray-500">|</span>
        <span style={{ color: rally.winner === 'player_a' ? WIN : LOSS }} className="font-medium">
          {winnerLabel} 得点
        </span>
        <span className="ml-auto text-gray-500 text-[10px]">
          {rally.score_a} – {rally.score_b}
        </span>
      </div>

      {/* ストローク列 */}
      {rally.rally_id == null ? (
        <p className="text-gray-600">ストロークデータなし（rally_id 未設定）</p>
      ) : isLoading ? (
        <p className="text-gray-600">読み込み中...</p>
      ) : strokes.length === 0 ? (
        <p className="text-gray-600">ストロークデータが記録されていません</p>
      ) : (
        <div className="flex flex-wrap gap-1 items-center">
          {strokes.map((s, i) => {
            const isA = s.player === 'player_a'
            const shotLabel = t(`shot_types.${s.shot_type}`, s.shot_type)
            const isLast = i === strokes.length - 1
            return (
              <span key={s.stroke_num} className="flex items-center gap-1">
                <span
                  className="px-1.5 py-0.5 rounded font-medium"
                  style={{
                    backgroundColor: isA ? 'rgba(59,130,246,0.18)' : 'rgba(239,68,68,0.18)',
                    color: isA ? '#93c5fd' : '#fca5a5',
                  }}
                >
                  {isA ? 'A' : 'B'} {shotLabel}
                  {s.hit_zone && <span className="text-[10px] opacity-60 ml-0.5">{s.hit_zone}</span>}
                </span>
                {!isLast && <span className="text-gray-600">→</span>}
              </span>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ─── メインコンポーネント ────────────────────────────────────────────────────

export function ScoreProgression({ matchId, onSetPointClick }: ScoreProgressionProps) {
  const { t } = useTranslation()
  const [selectedSet, setSelectedSet] = useState<number>(1)
  const [clickedRally, setClickedRally] = useState<(RallyPoint & { set_num: number }) | null>(null)

  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-score-progression', matchId],
    queryFn: () =>
      apiGet<ScoreProgressionResponse>('/analysis/score_progression', { match_id: matchId }),
    enabled: !!matchId,
  })

  if (isLoading) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.loading')}</div>
  }

  const sets = resp?.data?.sets ?? []
  const sampleSize = resp?.meta?.sample_size ?? 0

  if (sets.length === 0 || sampleSize === 0) {
    return (
      <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.no_data')}</div>
    )
  }

  const currentSet = sets.find((s) => s.set_num === selectedSet) ?? sets[0]
  const chartData = currentSet?.rallies ?? []

  return (
    <div className="space-y-3">
      <ConfidenceBadge sampleSize={sampleSize} />

      {/* セットセレクター */}
      {sets.length > 1 && (
        <div className="flex gap-1">
          {sets.map((s) => (
            <button
              key={s.set_num}
              onClick={() => { setSelectedSet(s.set_num); setClickedRally(null) }}
              className={`px-3 py-1 text-xs rounded font-medium transition-colors ${
                selectedSet === s.set_num
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
              }`}
            >
              {t('analysis.score_progression.set_selector')} {s.set_num}
            </button>
          ))}
        </div>
      )}

      {/* ラインチャート */}
      {chartData.length === 0 ? (
        <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.no_data')}</div>
      ) : (
        <ResponsiveContainer width="100%" height={220}>
          <LineChart
            data={chartData}
            margin={{ top: 10, right: 16, left: 0, bottom: 10 }}
            style={{ cursor: 'pointer' }}
            onClick={(chart) => {
              if (!chart?.activePayload?.[0]) return
              const point = chart.activePayload[0].payload as RallyPoint
              // ラリー詳細バナーをトグル（同じ点なら閉じる）
              if (clickedRally?.rally_num === point.rally_num && clickedRally?.set_num === currentSet?.set_num) {
                setClickedRally(null)
              } else {
                setClickedRally({ ...point, set_num: currentSet?.set_num ?? 1 })
              }
              // セット途中解析（onSetPointClick が渡された場合のみ）
              if (onSetPointClick && currentSet?.set_id != null) {
                onSetPointClick(currentSet.set_id, currentSet.set_num, point.rally_num, point.score_a, point.score_b)
              }
            }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
            <XAxis
              dataKey="rally_num"
              tick={{ fill: '#9ca3af', fontSize: 10 }}
              label={{
                value: t('analysis.score_progression.rally_num'),
                position: 'insideBottomRight',
                offset: -4,
                fill: '#6b7280',
                fontSize: 10,
              }}
            />
            <YAxis tick={{ fill: '#9ca3af', fontSize: 10 }} />
            <Tooltip content={<CustomTooltip />} />
            {/* 0点ライン（太線） */}
            <ReferenceLine y={0} stroke="#ffffff" strokeWidth={2} strokeDasharray="none" />
            {/* モメンタム変化点 */}
            {currentSet.momentum_changes.map((rallyNum) => (
              <ReferenceLine
                key={rallyNum}
                x={rallyNum}
                stroke="#f59e0b"
                strokeDasharray="4 2"
                strokeWidth={1}
              />
            ))}
            <Line
              type="monotone"
              dataKey="point_diff"
              stroke="#3b82f6"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, fill: '#60a5fa' }}
              name={t('analysis.score_progression.point_diff')}
            />
          </LineChart>
        </ResponsiveContainer>
      )}

      {/* ラリー詳細バナー */}
      {clickedRally && (
        <RallyDetailBanner
          rally={clickedRally}
          onClose={() => setClickedRally(null)}
          t={t}
        />
      )}

      <div className="flex gap-4 text-xs text-gray-500">
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-0.5 bg-blue-500" />
          A側リード ↑ / B側リード ↓
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-0.5 bg-yellow-500" style={{ borderTop: '1px dashed' }} />
          流れの変化点
        </span>
        <span className="text-blue-400">クリックでラリー詳細</span>
      </div>
    </div>
  )
}
