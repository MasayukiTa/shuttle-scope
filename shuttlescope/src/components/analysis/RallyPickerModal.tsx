/**
 * ラリー地点選択モーダル（速報タブ用）
 * スコア推移グラフ上の点をクリックしてラリー番号を選ぶ。
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  LineChart, Line, XAxis, YAxis, Tooltip,
  ResponsiveContainer, ReferenceLine, CartesianGrid,
} from 'recharts'
import { X } from 'lucide-react'
import { apiGet } from '@/api/client'
import { WIN, LOSS } from '@/styles/colors'
import { useIsLightMode } from '@/hooks/useIsLightMode'

interface RallyPoint {
  rally_num: number
  score_a: number
  score_b: number
  winner: string
  point_diff: number
}

interface SetData {
  set_id: number
  set_num: number
  rallies: RallyPoint[]
  momentum_changes: number[]
}

interface Props {
  matchId: number
  matchLabel: string
  initialSet: number
  selectedRallyNum: number | null
  onSelect: (setNum: number, rallyNum: number) => void
  onClear: () => void
  onClose: () => void
}

function CustomTooltip({ active, payload }: any) {
  const isLight = useIsLightMode()
  if (!active || !payload?.length) return null
  const d = payload[0]?.payload as RallyPoint
  if (!d) return null
  const bg = isLight ? '#ffffff' : '#1f2937'
  const border = isLight ? '#cbd5e1' : '#374151'
  const color = isLight ? '#0f172a' : '#f9fafb'
  const hintColor = isLight ? '#2563eb' : '#93c5fd'
  return (
    <div style={{ backgroundColor: bg, border: `1px solid ${border}`, borderRadius: 6, color, fontSize: 12, padding: '6px 10px' }}>
      <p className="font-semibold mb-0.5">ラリー {d.rally_num}</p>
      <p style={{ color: WIN }}>A: {d.score_a} &nbsp; <span style={{ color: LOSS }}>B: {d.score_b}</span></p>
      <p className="text-[10px] mt-0.5" style={{ color: hintColor }}>クリックで選択</p>
    </div>
  )
}

export function RallyPickerModal({ matchId, matchLabel, initialSet, selectedRallyNum, onSelect, onClear, onClose }: Props) {
  const isLight = useIsLightMode()
  const [activeSet, setActiveSet] = useState(initialSet)

  const { data: resp, isLoading } = useQuery({
    queryKey: ['rally-picker-score', matchId],
    queryFn: () => apiGet<{ success: boolean; data: { sets: SetData[] } }>('/analysis/score_progression', { match_id: matchId }),
    enabled: !!matchId,
  })

  const sets = resp?.data?.sets ?? []
  const currentSet = sets.find((s) => s.set_num === activeSet) ?? sets[0]
  const chartData = currentSet?.rallies ?? []

  const axisTick = isLight ? '#475569' : '#9ca3af'
  const gridColor = isLight ? '#e2e8f0' : '#374151'
  const bgStyle = isLight
    ? { backgroundColor: '#ffffff', border: '1px solid #e2e8f0' }
    : { backgroundColor: '#1e293b', border: '1px solid #334155' }

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="w-full max-w-2xl rounded-xl shadow-2xl" style={bgStyle}>
        {/* ヘッダー */}
        <div
          className="flex items-center justify-between px-5 py-3 border-b"
          style={{ borderColor: isLight ? '#e2e8f0' : '#334155' }}
        >
          <div>
            <p className="text-sm font-semibold" style={{ color: isLight ? '#1e293b' : '#f1f5f9' }}>
              ラリー地点を選択
            </p>
            <p className="text-xs mt-0.5" style={{ color: isLight ? '#64748b' : '#94a3b8' }}>
              {matchLabel}
            </p>
          </div>
          <button onClick={onClose} style={{ color: isLight ? '#64748b' : '#94a3b8' }} className="hover:opacity-70">
            <X size={18} />
          </button>
        </div>

        <div className="p-5 space-y-4">
          {/* セット切替ボタン */}
          {sets.length > 1 && (
            <div className="flex gap-1">
              {sets.map((s) => (
                <button
                  key={s.set_num}
                  onClick={() => setActiveSet(s.set_num)}
                  className={`px-3 py-1 text-xs rounded font-medium transition-colors ${
                    activeSet === s.set_num
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
                  }`}
                >
                  Set {s.set_num}
                </button>
              ))}
            </div>
          )}

          {/* グラフ */}
          {isLoading ? (
            <p className="text-sm text-gray-500 py-6 text-center">読み込み中...</p>
          ) : chartData.length === 0 ? (
            <p className="text-sm text-gray-500 py-6 text-center">データがありません</p>
          ) : (
            <>
              <p className="text-xs" style={{ color: isLight ? '#64748b' : '#94a3b8' }}>
                グラフの点をクリックして地点を選択してください
              </p>
              <ResponsiveContainer width="100%" height={220}>
                <LineChart
                  data={chartData}
                  margin={{ top: 10, right: 16, left: 0, bottom: 10 }}
                  style={{ cursor: 'pointer' }}
                  onClick={(chart) => {
                    if (!chart?.activePayload?.[0]) return
                    const point = chart.activePayload[0].payload as RallyPoint
                    const setNum = currentSet?.set_num ?? activeSet
                    onSelect(setNum, point.rally_num)
                    onClose()
                  }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
                  <XAxis dataKey="rally_num" tick={{ fill: axisTick, fontSize: 10 }} />
                  <YAxis tick={{ fill: axisTick, fontSize: 10 }} />
                  <Tooltip content={<CustomTooltip />} />
                  <ReferenceLine y={0} stroke={isLight ? '#94a3b8' : '#ffffff'} strokeWidth={1.5} />
                  {/* 現在選択中のラリー */}
                  {selectedRallyNum != null && (currentSet?.set_num ?? activeSet) === activeSet && (
                    <ReferenceLine
                      x={selectedRallyNum}
                      stroke="#f59e0b"
                      strokeWidth={2}
                      label={{ value: `R.${selectedRallyNum}`, fill: '#f59e0b', fontSize: 10, position: 'top' }}
                    />
                  )}
                  {currentSet?.momentum_changes.map((rn) => (
                    <ReferenceLine key={rn} x={rn} stroke="#f59e0b" strokeDasharray="4 2" strokeWidth={1} />
                  ))}
                  <Line
                    type="monotone"
                    dataKey="point_diff"
                    stroke="#3b82f6"
                    strokeWidth={2}
                    dot={false}
                    activeDot={{ r: 5, fill: '#60a5fa', stroke: '#ffffff', strokeWidth: 1.5 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </>
          )}

          {/* フッター */}
          <div className="flex items-center justify-between pt-1">
            <span className="text-xs" style={{ color: isLight ? '#64748b' : '#94a3b8' }}>
              {selectedRallyNum != null
                ? `選択中: Set ${activeSet} — ラリー ${selectedRallyNum}`
                : '未選択（全ラリーで解析）'}
            </span>
            <button
              onClick={() => { onClear(); onClose() }}
              className="text-xs px-3 py-1 rounded bg-gray-700 text-gray-300 hover:bg-gray-600"
            >
              全ラリーで解析
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
