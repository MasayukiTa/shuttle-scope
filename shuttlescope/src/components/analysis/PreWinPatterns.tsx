// R-003: 得点前パターン（PreLossPatterns の勝ち版）
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { AnalysisFilters, DEFAULT_FILTERS } from '@/types'
import { WIN } from '@/styles/colors'

interface PreWinPatternsProps {
  playerId: number
  filters?: AnalysisFilters
}

interface ShotPattern {
  shot_type: string
  shot_type_ja: string
  count: number
  rate: number
}

interface PreWinResponse {
  success: boolean
  data: {
    pre_win_1: ShotPattern[]
    pre_win_2: ShotPattern[]
    pre_win_3: ShotPattern[]
  }
  meta: { sample_size: number; confidence: { level: string; stars: string; label: string } }
}

type PreKey = 'pre_win_1' | 'pre_win_2' | 'pre_win_3'

function PatternList({ patterns }: { patterns: ShotPattern[] }) {
  const { t } = useTranslation()
  if (patterns.length === 0) {
    return <p className="text-gray-500 text-sm py-2">{t('analysis.no_data')}</p>
  }
  return (
    <div className="space-y-1.5">
      {patterns.slice(0, 8).map((p) => (
        <div key={p.shot_type} className="flex items-center gap-2">
          <span className="w-28 shrink-0 text-xs text-gray-300 truncate">{p.shot_type_ja}</span>
          <div className="flex-1 bg-gray-700 rounded-full h-1.5">
            <div
              className="h-1.5 rounded-full transition-all"
              style={{ width: `${Math.min(p.rate * 100, 100).toFixed(1)}%`, backgroundColor: WIN }}
            />
          </div>
          <span className="w-10 text-right text-xs text-gray-400 shrink-0">
            {(p.rate * 100).toFixed(1)}%
          </span>
        </div>
      ))}
    </div>
  )
}

export function PreWinPatterns({ playerId, filters = DEFAULT_FILTERS }: PreWinPatternsProps) {
  const { t } = useTranslation()
  const [activeTab, setActiveTab] = useState<PreKey>('pre_win_1')

  const fp = {
    ...(filters.result !== 'all' ? { result: filters.result } : {}),
    ...(filters.tournamentLevel ? { tournament_level: filters.tournamentLevel } : {}),
    ...(filters.dateFrom ? { date_from: filters.dateFrom } : {}),
    ...(filters.dateTo ? { date_to: filters.dateTo } : {}),
  }

  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-pre-win-patterns', playerId, filters],
    queryFn: () =>
      apiGet<PreWinResponse>('/analysis/pre_win_patterns', { player_id: playerId, ...fp }),
    enabled: !!playerId,
  })

  if (isLoading) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.loading')}</div>
  }

  const sampleSize = resp?.meta?.sample_size ?? 0
  const data = resp?.data

  if (!data || sampleSize === 0) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.no_data')}</div>
  }

  const tabs: { key: PreKey; label: string }[] = [
    { key: 'pre_win_1', label: t('analysis.pre_win.pre1') },
    { key: 'pre_win_2', label: t('analysis.pre_win.pre2') },
    { key: 'pre_win_3', label: t('analysis.pre_win.pre3') },
  ]

  return (
    <div className="space-y-3">
      <ConfidenceBadge sampleSize={sampleSize} />

      <div className="flex gap-1">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`px-3 py-1 text-xs rounded font-medium transition-colors ${
              activeTab === tab.key
                ? ''
                : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
            }`}
            style={activeTab === tab.key ? { backgroundColor: WIN, color: '#ffffff' } : {}}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <PatternList patterns={data[activeTab] ?? []} />
    </div>
  )
}
