// 対戦相手別ショット有効性コンポーネント（アナリスト・コーチ向け）
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { NoDataMessage } from '@/components/common/NoDataMessage'
import { RoleGuard } from '@/components/common/RoleGuard'
import { perfColor, BAR, AXIS_TICK } from '@/styles/colors'

interface OpponentAdaptiveShotsProps {
  playerId: number
}

interface ShotEffectiveness {
  shot_type: string
  shot_label: string
  count: number
  win_rate: number
  lift: number
}

interface OpponentEntry {
  opponent_id: number
  opponent_name: string
  match_count: number
  shot_effectiveness: ShotEffectiveness[]
}

interface Response {
  success: boolean
  data: {
    global_shot_winrates: Record<string, number>
    opponents: OpponentEntry[]
  }
  meta: { sample_size: number; confidence: { level: string; stars: string; label: string } }
}

function ShotBar({ label, winRate, lift, count }: { label: string; winRate: number; lift: number; count: number }) {
  const pct = Math.round(winRate * 100)
  const liftPositive = lift >= 0
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-28 text-right text-gray-300 truncate shrink-0">{label}</span>
      <div className="flex-1 bg-gray-700 rounded h-4 relative overflow-hidden">
        <div
          className="h-full rounded transition-all"
          style={{ width: `${pct}%`, backgroundColor: perfColor(winRate) }}
        />
        <span className="absolute inset-0 flex items-center justify-center text-white text-xs font-mono">
          {pct}%
        </span>
      </div>
      <span className={`text-xs font-mono w-12 text-right ${liftPositive ? 'text-blue-400' : 'text-red-400'}`}>
        {liftPositive ? '+' : ''}{Math.round(lift * 100)}%
      </span>
      <span className="text-gray-500 text-xs w-8 text-right">{count}</span>
    </div>
  )
}

function Inner({ playerId }: { playerId: number }) {
  const [selected, setSelected] = useState<number | null>(null)

  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-opponent-adaptive-shots', playerId],
    queryFn: () => apiGet<Response>('/analysis/opponent_adaptive_shots', { player_id: playerId }),
    enabled: !!playerId,
  })

  if (isLoading) {
    return <div className="text-gray-500 text-sm py-4 text-center">読み込み中...</div>
  }

  const opponents = resp?.data?.opponents ?? []
  const sampleSize = resp?.meta?.sample_size ?? 0

  if (opponents.length === 0) {
    return <NoDataMessage sampleSize={sampleSize} minRequired={5} unit="試合" />
  }

  const activeOpp = selected !== null ? opponents.find(o => o.opponent_id === selected) : opponents[0]

  return (
    <div className="space-y-3">
      <ConfidenceBadge sampleSize={sampleSize} />

      {/* 対戦相手タブ */}
      <div className="flex flex-wrap gap-1">
        {opponents.map(o => (
          <button
            key={o.opponent_id}
            onClick={() => setSelected(o.opponent_id)}
            className={`px-2 py-1 rounded text-xs transition-colors ${
              (selected === null ? opponents[0].opponent_id : selected) === o.opponent_id
                ? 'bg-blue-600 text-white'
                : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
            }`}
          >
            {o.opponent_name}
            <span className="ml-1 text-gray-400">({o.match_count}試合)</span>
          </button>
        ))}
      </div>

      {/* ショット別グラフ */}
      {activeOpp && (
        <div className="space-y-1.5">
          <div className="flex items-center justify-between text-xs text-gray-400 mb-2">
            <span>ショット種別 勝率 vs {activeOpp.opponent_name}</span>
            <span className="text-gray-500">lift=全体比</span>
          </div>
          {activeOpp.shot_effectiveness.length === 0 ? (
            <NoDataMessage sampleSize={0} minRequired={3} unit="回" />
          ) : (
            activeOpp.shot_effectiveness.map(s => (
              <ShotBar
                key={s.shot_type}
                label={s.shot_label}
                winRate={s.win_rate}
                lift={s.lift}
                count={s.count}
              />
            ))
          )}
        </div>
      )}
    </div>
  )
}

export function OpponentAdaptiveShots({ playerId }: OpponentAdaptiveShotsProps) {
  return (
    <RoleGuard allowedRoles={['analyst', 'coach']}>
      <div className="bg-gray-800 rounded-lg p-4">
        <h3 className="text-sm font-semibold text-gray-200 mb-3">対戦相手別ショット有効性</h3>
        <Inner playerId={playerId} />
      </div>
    </RoleGuard>
  )
}
