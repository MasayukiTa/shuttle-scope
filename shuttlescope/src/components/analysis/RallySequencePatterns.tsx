// ラリー3連ショットパターン — 勝ちパターン/負けパターン表示
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'
import { useReviewBundleSlice } from '@/contexts/ReviewBundleContext'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { NoDataMessage } from '@/components/common/NoDataMessage'
import { WIN, LOSS, perfColor } from '@/styles/colors'
import { useTranslation } from 'react-i18next'

interface RallySequencePatternsProps {
  playerId: number
}

interface SequenceEntry {
  sequence: string[]
  labels: string[]
  count: number
  win_rate: number
  win_count: number
}

interface Response {
  success: boolean
  data: {
    win_sequences: SequenceEntry[]
    loss_sequences: SequenceEntry[]
    total_rallies: number
  }
  meta: { sample_size: number; confidence: { level: string; stars: string; label: string } }
}

function SequencePill({ labels, winRate }: { labels: string[]; winRate: number }) {
  const { t } = useTranslation()

  return (
    <div className="flex items-center gap-1 flex-wrap">
      {labels.map((label, i) => (
        <span key={i} className="flex items-center gap-1">
          <span
            className="px-2 py-0.5 rounded text-xs font-medium"
            style={{ backgroundColor: perfColor(winRate, 0.85), color: '#ffffff' }}
          >
            {label}
          </span>
          {i < labels.length - 1 && (
            <span className="text-gray-500 text-xs">→</span>
          )}
        </span>
      ))}
    </div>
  )
}

function SequenceList({ sequences, accent, title }: { sequences: SequenceEntry[]; accent: string; title: string }) {
  const { t } = useTranslation()

  return (
    <div className="flex-1 min-w-0">
      <h4 className="text-xs font-semibold mb-2 pb-1 border-b border-gray-700" style={{ color: accent }}>
        {title}
      </h4>
      {sequences.length === 0 ? (
        <p className="text-xs text-gray-500 py-2">{t('auto.RallySequencePatterns.k1')}</p>
      ) : (
        <div className="space-y-2">
          {sequences.map((s, i) => (
            <div key={i} className="space-y-1">
              <SequencePill labels={s.labels} winRate={s.win_rate} />
              <div className="flex gap-3 text-xs text-gray-400 pl-1">
                <span>{s.count}回</span>
                <span className="font-mono">{Math.round(s.win_rate * 100)}%</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export function RallySequencePatterns({ playerId }: RallySequencePatternsProps) {
  const { t } = useTranslation()

  // bundle 提供時はスライスを使用
  const { slice: bundled, loading: bundleLoading, provided } = useReviewBundleSlice<Response>('rally_sequence_patterns')
  const indiv = useQuery({
    queryKey: ['analysis-rally-sequence-patterns', playerId],
    queryFn: () => apiGet<Response>('/analysis/rally_sequence_patterns', { player_id: playerId }),
    enabled: !!playerId && !provided && !bundleLoading,
  })
  const resp = bundled ?? indiv.data
  const isLoading = provided ? bundleLoading : indiv.isLoading

  if (isLoading) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('auto.RallySequencePatterns.k2')}</div>
  }

  const winSeqs = resp?.data?.win_sequences ?? []
  const lossSeqs = resp?.data?.loss_sequences ?? []
  const totalRallies = resp?.data?.total_rallies ?? 0
  const sampleSize = resp?.meta?.sample_size ?? 0

  if (winSeqs.length === 0 && lossSeqs.length === 0) {
    return (
      <div className="bg-gray-800 rounded-lg p-4">
        <h3 className="text-sm font-semibold text-gray-200 mb-3">{t('auto.RallySequencePatterns.k3')}</h3>
        <NoDataMessage sampleSize={totalRallies} minRequired={20} unit="ラリー" />
      </div>
    )
  }

  return (
    <div className="bg-gray-800 rounded-lg p-4">
      <h3 className="text-sm font-semibold text-gray-200 mb-1">{t('auto.RallySequencePatterns.k3')}</h3>
      <p className="text-xs text-gray-500 mb-3">分析ラリー数: {totalRallies}</p>
      <ConfidenceBadge sampleSize={sampleSize} />
      <div className="flex gap-4 mt-3">
        <SequenceList sequences={winSeqs} accent={WIN} title={t('auto.RallySequencePatterns.k4')} />
        <div className="w-px bg-gray-700 self-stretch" />
        <SequenceList sequences={lossSeqs} accent={LOSS} title={t('auto.RallySequencePatterns.k5')} />
      </div>
    </div>
  )
}
