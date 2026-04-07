// ペアシミュレーションパネル — Phase B
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { SetDistributionBar } from '@/components/analysis/SetDistributionBar'
import { WIN, LOSS } from '@/styles/colors'
import { useIsLightMode } from '@/hooks/useIsLightMode'

interface PlayerSummary {
  id: number
  name: string
  team?: string
}

interface PairSimResponse {
  success: boolean
  data: {
    pair_name: string
    win_probability: number
    set_distribution: { '2-0': number; '2-1': number; '1-2': number; '0-2': number }
    pair_strengths: string[]
    pair_cautions: string[]
    confidence: number
    sample_size: number
  }
  meta: { sample_size: number; confidence: { level: string; stars: string; label: string } }
}

interface PairSimulationPanelProps {
  players: PlayerSummary[]
}

function winProbColor(p: number, isLight: boolean): string {
  const neutral = isLight ? '#1e293b' : '#e2e8f0'
  if (p >= 0.55) return WIN
  if (p <= 0.45) return LOSS
  return neutral
}

export function PairSimulationPanel({ players }: PairSimulationPanelProps) {
  const { t } = useTranslation()
  const isLight = useIsLightMode()
  const [pid1, setPid1] = useState<number | null>(null)
  const [pid2, setPid2] = useState<number | null>(null)
  const [level, setLevel] = useState('')
  const [run, setRun] = useState(false)

  const neutral = isLight ? '#334155' : '#d1d5db'
  const subText = isLight ? '#64748b' : '#9ca3af'

  const { data: resp, isLoading } = useQuery({
    queryKey: ['pair-simulation', pid1, pid2, level],
    queryFn: () =>
      apiGet<PairSimResponse>('/prediction/pair_simulation', {
        player_id_1: pid1!,
        player_id_2: pid2!,
        ...(level ? { tournament_level: level } : {}),
      }),
    enabled: run && pid1 != null && pid2 != null && pid1 !== pid2,
  })

  const selectClass = `text-xs rounded px-2 py-1.5 focus:outline-none ${
    isLight
      ? 'bg-white border border-gray-300 text-gray-800'
      : 'bg-gray-700 border border-gray-600 text-gray-200'
  }`

  const d = resp?.data

  return (
    <div className="space-y-4">
      {/* セレクター */}
      <div className="flex gap-2 flex-wrap items-end">
        <div className="space-y-1">
          <p className="text-[10px]" style={{ color: subText }}>{t('prediction.pair_select_1')}</p>
          <select value={pid1 ?? ''} onChange={(e) => { setPid1(e.target.value ? Number(e.target.value) : null); setRun(false) }} className={selectClass}>
            <option value="">— 選手1 —</option>
            {players.map((p) => (
              <option key={p.id} value={p.id}>{p.name}{p.team ? `（${p.team}）` : ''}</option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <p className="text-[10px]" style={{ color: subText }}>{t('prediction.pair_select_2')}</p>
          <select value={pid2 ?? ''} onChange={(e) => { setPid2(e.target.value ? Number(e.target.value) : null); setRun(false) }} className={selectClass}>
            <option value="">— 選手2 —</option>
            {players.filter((p) => p.id !== pid1).map((p) => (
              <option key={p.id} value={p.id}>{p.name}{p.team ? `（${p.team}）` : ''}</option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <p className="text-[10px]" style={{ color: subText }}>大会レベル</p>
          <select value={level} onChange={(e) => { setLevel(e.target.value); setRun(false) }} className={selectClass}>
            <option value="">— 全レベル —</option>
            {['IC', 'IS', 'SJL', '全日本', '国内'].map((lv) => (
              <option key={lv} value={lv}>{lv}</option>
            ))}
          </select>
        </div>
        <button
          onClick={() => setRun(true)}
          disabled={!pid1 || !pid2 || pid1 === pid2}
          className="px-3 py-1.5 rounded text-xs font-medium bg-gray-600 hover:bg-gray-500 text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {t('prediction.run_simulation')}
        </button>
      </div>

      {/* 結果 */}
      {isLoading && (
        <div className="text-gray-500 text-sm py-4 text-center">{t('prediction.loading')}</div>
      )}

      {d && (
        <div className="bg-gray-800 rounded-lg p-4 space-y-4">
          <div className="flex items-center gap-3 flex-wrap">
            <span className="text-sm font-semibold" style={{ color: neutral }}>{d.pair_name}</span>
            <ConfidenceBadge sampleSize={d.sample_size} />
            <span className="text-xs" style={{ color: subText }}>{d.sample_size}試合</span>
          </div>

          {/* 勝率 */}
          <div className="text-center">
            <p className="text-4xl font-bold" style={{ color: winProbColor(d.win_probability, isLight) }}>
              {Math.round(d.win_probability * 100)}%
            </p>
            <p className="text-xs mt-1" style={{ color: subText }}>{t('prediction.win_probability')}</p>
          </div>

          {/* セット分布 */}
          {d.sample_size > 0 && (
            <div>
              <p className="text-xs font-medium mb-2" style={{ color: subText }}>{t('prediction.set_distribution')}</p>
              <SetDistributionBar distribution={d.set_distribution} />
            </div>
          )}

          {/* 強み・注意点 */}
          {d.pair_strengths.length > 0 && (
            <ul className="space-y-1">
              {d.pair_strengths.map((s, i) => (
                <li key={i} className="text-xs" style={{ color: WIN }}>✓ {s}</li>
              ))}
            </ul>
          )}
          {d.pair_cautions.length > 0 && (
            <ul className="space-y-1">
              {d.pair_cautions.map((c, i) => (
                <li key={i} className="text-xs" style={{ color: subText }}>⚠ {c}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
