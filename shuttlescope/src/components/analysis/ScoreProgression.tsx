// スコア推移グラフコンポーネント（ラリーごとの点差変化をラインチャートで表示）
import { useState } from 'react'
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
import { WIN, LOSS, TOOLTIP_STYLE } from '@/styles/colors'

interface ScoreProgressionProps {
  matchId: number
}

interface RallyPoint {
  rally_num: number
  score_a: number
  score_b: number
  winner: string
  point_diff: number
}

interface SetData {
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

export function ScoreProgression({ matchId }: ScoreProgressionProps) {
  const { t } = useTranslation()
  const [selectedSet, setSelectedSet] = useState<number>(1)

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
              onClick={() => setSelectedSet(s.set_num)}
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

      <div className="flex gap-4 text-xs text-gray-500">
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-0.5 bg-blue-500" />
          A側リード ↑ / B側リード ↓
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-0.5 bg-yellow-500" style={{ borderTop: '1px dashed' }} />
          流れの変化点
        </span>
      </div>
    </div>
  )
}
