// Phase 3: ペア別プレースタイル分類（前衛主体/後衛主体/バランス型）
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { WIN } from '@/styles/colors'
import { useIsLightMode } from '@/hooks/useIsLightMode'

interface PairPlaystyleProps {
  playerAId: number
  playerBId: number
  playerAName?: string
  playerBName?: string
}

interface PairPlaystyleResponse {
  success: boolean
  data: {
    playstyle: string
    playstyle_en: string
    zone_distribution: Record<string, number>
    metrics: {
      net_zone_rate: number
      back_zone_rate: number
      mid_zone_rate: number
      smash_rate: number
      net_shot_rate: number
      match_count: number
    }
  }
  meta: { sample_size: number; confidence: { level: string; stars: string; label: string } }
}

const PLAYSTYLE_COLOR: Record<string, { text: string; lightText: string; bg: string; border: string }> = {
  net_dominant:  { text: '#3b82f6', lightText: '#1d4ed8', bg: 'rgba(59,130,246,0.1)',  border: '#3b82f6' },
  back_dominant: { text: '#8b5cf6', lightText: '#6d28d9', bg: 'rgba(139,92,246,0.1)', border: '#8b5cf6' },
  balanced:      { text: '#06b6d4', lightText: '#0e7490', bg: 'rgba(6,182,212,0.1)',   border: '#06b6d4' },
  unknown:       { text: '#6b7280', lightText: '#4b5563', bg: 'rgba(107,114,128,0.1)', border: '#6b7280' },
}

const METRIC_ROWS = [
  { key: 'net_zone_rate',  label: 'ネット前配球率' },
  { key: 'back_zone_rate', label: '奥配球率' },
  { key: 'mid_zone_rate',  label: '中間配球率' },
  { key: 'smash_rate',     label: 'スマッシュ率' },
  { key: 'net_shot_rate',  label: 'ネットショット率' },
]

export function PairPlaystyle({ playerAId, playerBId, playerAName = 'A', playerBName = 'B' }: PairPlaystyleProps) {
  const { t } = useTranslation()
  const isLight = useIsLightMode()

  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-pair-playstyle', playerAId, playerBId],
    queryFn: () =>
      apiGet<PairPlaystyleResponse>('/analysis/pair_playstyle', {
        player_a_id: playerAId,
        player_b_id: playerBId,
      }),
    enabled: !!playerAId && !!playerBId,
  })

  if (isLoading) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.loading')}</div>
  }

  const sampleSize = resp?.meta?.sample_size ?? 0
  const d = resp?.data

  if (!d || sampleSize === 0) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.no_data')}</div>
  }

  const styleKey = d.playstyle_en ?? 'unknown'
  const styleConf = PLAYSTYLE_COLOR[styleKey] ?? PLAYSTYLE_COLOR.unknown
  const textColor  = isLight ? styleConf.lightText : styleConf.text
  const labelColor = isLight ? '#475569' : '#9ca3af'
  const trackBg   = isLight ? '#e2e8f0' : '#374151'

  return (
    <div className="space-y-3">
      <ConfidenceBadge sampleSize={sampleSize} />

      {/* プレースタイルバッジ */}
      <div
        className="rounded-lg px-4 py-3 flex items-center gap-3"
        style={{ backgroundColor: styleConf.bg, border: `1.5px solid ${styleConf.border}` }}
      >
        <div>
          <p className="text-xs" style={{ color: labelColor }}>
            {playerAName} / {playerBName} のプレースタイル
          </p>
          <p className="text-lg font-bold" style={{ color: textColor }}>
            {d.playstyle}
          </p>
        </div>
        <div className="ml-auto text-right">
          <p className="text-xs" style={{ color: labelColor }}>
            {d.metrics.match_count}試合
          </p>
        </div>
      </div>

      {/* 指標バー */}
      <div className="space-y-2">
        {METRIC_ROWS.map(({ key, label }) => {
          const val = d.metrics[key as keyof typeof d.metrics] as number ?? 0
          return (
            <div key={key}>
              <div className="flex justify-between mb-0.5">
                <span className="text-xs" style={{ color: labelColor }}>{label}</span>
                <span className="text-xs font-mono" style={{ color: textColor }}>
                  {(val * 100).toFixed(1)}%
                </span>
              </div>
              <div className="w-full rounded-full h-1.5 overflow-hidden" style={{ backgroundColor: trackBg }}>
                <div
                  className="h-1.5 rounded-full transition-all"
                  style={{ width: `${Math.min(val * 100, 100).toFixed(0)}%`, backgroundColor: styleConf.border }}
                />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
